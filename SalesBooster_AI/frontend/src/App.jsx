import React, { useState, useEffect, useMemo, useRef } from 'react';
import './App.css';
import { apiUrl } from './api';

function App() {
  const looksLikeJwt = (value) => {
    if (!value || typeof value !== 'string') return false;
    const parts = value.split('.');
    return parts.length === 3 && parts.every((p) => p.length > 0);
  };

  const getInitialToken = () => {
    const stored = localStorage.getItem('token');
    if (!looksLikeJwt(stored)) {
      localStorage.removeItem('token');
      return null;
    }
    return stored;
  };

  const [token, setToken] = useState(getInitialToken());
  const [activeTab, setActiveTab] = useState('keyword'); // keyword, direct, audit, leads, mailer
  const [loading, setLoading] = useState(false);
  
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [isLogin, setIsLogin] = useState(true);

  const [keyword, setKeyword] = useState('');
  const [targetUrl, setTargetUrl] = useState('');
  const [leadSearch, setLeadSearch] = useState('');
  const [leadStatusFilter, setLeadStatusFilter] = useState('all');
  const [leadIntentFilter, setLeadIntentFilter] = useState('all');
  const [importingCsv, setImportingCsv] = useState(false);
  const csvInputRef = useRef(null);

  const [leads, setLeads] = useState([]);
  const [selectedLeads, setSelectedLeads] = useState(new Set());
  const [audit, setAudit] = useState(null);
  const [discoveryResult, setDiscoveryResult] = useState(null);
  const [keywordResult, setKeywordResult] = useState(null);
  const [analytics, setAnalytics] = useState({
    total_leads: 0,
    avg_lead_score: 0,
    status_breakdown: { new: 0, contacted: 0, replied: 0, meeting: 0, won: 0, lost: 0 }
  });
  const [smtpStatus, setSmtpStatus] = useState({ configured: false, host: '', port: '', sender: '' });
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('Hi {email},\n\nWe saw you ranking for your keywords but noticed you lack a modern web presence. Our agency can build you a state-of-the-art platform.\n\nLet\'s chat!');
  const [notice, setNotice] = useState({ type: '', message: '' });

  const showNotice = (type, message) => setNotice({ type, message });
  const parseApiResponse = async (res) => {
    const text = await res.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch {
      return { detail: text || `HTTP ${res.status}` };
    }
  };

  const formatFetchError = (data, res) => {
    const raw = data?.detail ?? data?.message ?? data?.error;
    if (typeof raw === 'string' && raw.trim()) {
      const t = raw.trim();
      if (t.startsWith('<!DOCTYPE') || t.toLowerCase().startsWith('<html')) {
        return `Server returned ${res.status} (HTML instead of JSON). Confirm the Vite proxy targets the SalesBooster Django port.`;
      }
      return t.length > 240 ? `${t.slice(0, 240)}…` : t;
    }
    return `Request failed (${res.status})`;
  };

  const auditSummaryText = (a) => {
    if (!a) return '';
    const issues = (a.critical_issues_found || []).map((line) => `• ${line}`).join('\n');
    return [
      `Tech audit — ${a.url}`,
      `Score: ${a.performance_score} | Status: ${a.status}`,
      issues,
      a.outreach_summary ? `\nOutreach: ${a.outreach_summary}` : '',
    ]
      .filter(Boolean)
      .join('\n');
  };

  const copyAuditSummary = async () => {
    if (!audit) return;
    try {
      await navigator.clipboard.writeText(auditSummaryText(audit));
      showNotice('success', 'Executive summary copied to clipboard.');
    } catch {
      showNotice('error', 'Could not copy to clipboard.');
    }
  };

  const getLeadWebsite = (lead) => lead.website_url || lead.source_url || '';

  const filteredLeads = useMemo(() => {
    const needle = leadSearch.trim().toLowerCase();
    return leads.filter((lead) => {
      const statusOk = leadStatusFilter === 'all' || (lead.status || 'new') === leadStatusFilter;
      const intentOk = leadIntentFilter === 'all' || (lead.intent_type || 'awareness') === leadIntentFilter;
      if (!statusOk || !intentOk) return false;
      if (!needle) return true;
      const haystack = [
        lead.contact_name || '',
        lead.keyword || '',
        lead.email || '',
        lead.phone || '',
        lead.source_url || '',
        lead.website_url || '',
      ]
        .join(' ')
        .toLowerCase();
      return haystack.includes(needle);
    });
  }, [leads, leadSearch, leadStatusFilter, leadIntentFilter]);

  const exportLeadsCsv = () => {
    if (!filteredLeads.length) {
      showNotice('warning', 'No rows to export for current filters.');
      return;
    }
    const escapeCell = (v) => `"${String(v ?? '').replace(/"/g, '""')}"`;
    const rows = [
      ['Name/Org', 'Keyword/Source', 'Intent', 'Score', 'Extracted Email', 'Phone', 'Website', 'Status'],
      ...filteredLeads.map((lead) => [
        lead.contact_name || 'Unknown',
        lead.keyword || '',
        lead.intent_type || 'awareness',
        lead.lead_score ?? 0,
        lead.email === 'not_found' ? 'Not found' : lead.email,
        lead.phone && lead.phone !== 'not_found' ? lead.phone : 'N/A',
        getLeadWebsite(lead) || 'N/A',
        lead.status || 'new',
      ]),
    ];
    const csv = rows.map((row) => row.map(escapeCell).join(',')).join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const stamp = new Date().toISOString().slice(0, 10);
    const a = document.createElement('a');
    a.href = url;
    a.download = `salesbooster-leads-${stamp}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showNotice('success', `Exported ${filteredLeads.length} lead(s) to CSV.`);
  };

  const openCsvPicker = () => {
    if (csvInputRef.current) csvInputRef.current.click();
  };

  const downloadCsvTemplate = () => {
    const template =
      'name,email,phone,website,keyword,status\n' +
      'John Doe,john@example.com,+911234567890,https://example.com,digital marketing,new\n';
    const blob = new Blob([template], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'salesbooster-import-template.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  const handleCsvImport = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.csv')) {
      showNotice('error', 'Please upload a .csv file.');
      return;
    }
    setImportingCsv(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch(apiUrl('/api/leads/import-csv'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      });
      const data = await parseApiResponse(res);
      if (res.ok) {
        const created = data.created ?? 0;
        const skipped = data.skipped ?? 0;
        showNotice(
          created > 0 ? 'success' : 'warning',
          `CSV imported: ${created} created, ${skipped} skipped.`
        );
        fetchLeads();
        fetchAnalytics();
      } else if (res.status === 401) {
        handleAuthFailure();
      } else {
        showNotice('error', formatFetchError(data, res));
      }
    } catch {
      showNotice('error', 'CSV import failed. Please try again.');
    } finally {
      setImportingCsv(false);
    }
  };

  useEffect(() => {
    if (token) {
      fetchLeads();
      fetchAnalytics();
      fetchSmtpStatus();
    }
  }, [token]);

  useEffect(() => {
    if (token && activeTab === 'leads') {
      fetchLeads();
      fetchAnalytics();
    }
  }, [token, activeTab]);

  useEffect(() => {
    if (!notice.message) return undefined;
    const timer = setTimeout(() => setNotice({ type: '', message: '' }), 5000);
    return () => clearTimeout(timer);
  }, [notice.message]);

  const authHeader = {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${token}`
  };

  const handleAuth = async () => {
    if (username.trim().length < 3) {
      showNotice('warning', 'Username must be at least 3 characters.');
      return;
    }
    if (password.length < 6) {
      showNotice('warning', 'Password must be at least 6 characters.');
      return;
    }
    setLoading(true);
    const endpoint = isLogin ? '/api/login' : '/api/register';
    try {
      const res = await fetch(apiUrl(endpoint), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      const data = await res.json();
      if (res.ok) {
        if (isLogin) {
          const authToken = data.access || data.access_token;
          localStorage.setItem('token', authToken);
          setToken(authToken);
        } else {
          showNotice('success', 'Registered successfully. Please login.');
          setIsLogin(true);
        }
      } else {
        showNotice('error', data.detail || 'Auth failed');
      }
    } catch (e) {
      showNotice('error', 'Network Error');
    }
    setLoading(false);
  };

  const handleLogout = () => {
    localStorage.removeItem('token');
    setToken(null);
    setNotice({ type: '', message: '' });
  };

  const handleAuthFailure = () => {
    localStorage.removeItem('token');
    setToken(null);
    showNotice('error', 'Session expired or invalid token. Please login again.');
  };

  const fetchLeads = async () => {
    try {
      const res = await fetch(apiUrl('/api/leads'), { headers: authHeader });
      const data = await parseApiResponse(res);
      if (res.ok) {
        setLeads(Array.isArray(data) ? data : []);
      } else if (res.status === 401) {
        handleAuthFailure();
      } else {
        showNotice('error', formatFetchError(data, res));
      }
    } catch (e) {
      console.error(e);
      showNotice('error', 'Could not load leads from the server.');
    }
  };

  const fetchAnalytics = async () => {
    try {
      const res = await fetch(apiUrl('/api/analytics'), { headers: authHeader });
      const data = await parseApiResponse(res);
      if (res.ok) {
        setAnalytics(data);
      } else if (res.status === 401) {
        handleAuthFailure();
      } else {
        showNotice('error', formatFetchError(data, res));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const fetchSmtpStatus = async () => {
    try {
      const res = await fetch(apiUrl('/api/smtp-status'), { headers: authHeader });
      const data = await parseApiResponse(res);
      if (res.ok) {
        setSmtpStatus(data);
      } else if (res.status === 401) {
        handleAuthFailure();
      } else {
        showNotice('error', formatFetchError(data, res));
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleKeywordSearch = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    setKeywordResult(null);
    try {
      const res = await fetch(apiUrl('/api/keyword-search'), {
        method: 'POST',
        headers: authHeader,
        body: JSON.stringify({ keyword })
      });
      const data = await parseApiResponse(res);
      if (res.ok) {
        setKeywordResult(data);
        const added = data.new_leads_found ?? 0;
        const existing = data.existing_leads_found ?? 0;
        const attempted = data.attempted_rows ?? 0;
        const scrapeFailed = data.scrape_failed_urls_count ?? 0;
        const createFailed = data.create_failed_rows ?? 0;
        const dupes = data.duplicate_rows ?? 0;
        if (added === 0) {
          if (existing > 0) {
            showNotice(
              'success',
              `No new leads added, but ${existing} matching leads already exist in your database.`
            );
          } else {
            const reasonParts = [];
            if (data.detail) reasonParts.push(data.detail);
            if (attempted > 0) reasonParts.push(`attempted ${attempted}`);
            if (dupes > 0) reasonParts.push(`duplicates ${dupes}`);
            if (scrapeFailed > 0) reasonParts.push(`scrape failed on ${scrapeFailed} site(s)`);
            if (createFailed > 0) reasonParts.push(`save failed for ${createFailed} row(s)`);
            showNotice('warning', `No new rows added${reasonParts.length ? ` (${reasonParts.join(', ')})` : ''}. Try another keyword/location.`);
          }
        } else {
          showNotice(
            'success',
            existing > 0
              ? `Added ${added} new lead(s) and found ${existing} existing lead(s).`
              : `Added ${added} new lead(s). Open Lead Manager to review.`
          );
        }
        fetchLeads();
        fetchAnalytics();
      } else {
        if (res.status === 401) {
          handleAuthFailure();
          return;
        }
        showNotice('error', data.detail || 'Search failed');
      }
    } catch (e) {
      showNotice('error', 'Search failed');
    }
    setLoading(false);
  };

  const handleDirectScrape = async () => {
    if (!targetUrl.trim()) return;
    setLoading(true);
    setDiscoveryResult(null);
    try {
      const res = await fetch(apiUrl('/api/scrape-url'), {
        method: 'POST',
        headers: authHeader,
        body: JSON.stringify({ url: targetUrl })
      });
      const data = await parseApiResponse(res);
      if (res.ok) {
        setDiscoveryResult(data.discovery || null);
        if (data.status === 'partial') {
          showNotice('warning', data.detail || 'Scrape was blocked; check discovery below and Lead Manager for any placeholder row.');
        } else {
          const n = data.new_leads_found ?? 0;
          showNotice(
            n > 0 ? 'success' : 'warning',
            n > 0 ? `Saved ${n} new lead(s). Discovery data is below.` : 'Scrape returned no new unique rows (may already exist).'
          );
        }
        fetchLeads();
        fetchAnalytics();
      } else {
        if (res.status === 401) {
          handleAuthFailure();
          return;
        }
        showNotice('error', data.detail || 'Scraping failed');
      }
    } catch (e) {
      showNotice('error', 'Scraping failed');
    }
    setLoading(false);
  };

  const handleAudit = async () => {
    if (!targetUrl.trim()) return;
    setLoading(true);
    setAudit(null);
    try {
      const res = await fetch(apiUrl('/api/audit'), {
        method: 'POST',
        headers: authHeader,
        body: JSON.stringify({ url: targetUrl })
      });
      const data = await parseApiResponse(res);
      if (res.ok) {
        if (!data.audit) {
          setAudit(null);
          showNotice('error', 'Server returned success but no audit payload.');
        } else {
          setAudit(data.audit);
          if (data.status === 'degraded') {
            showNotice('warning', data.detail || 'Showing a fallback audit after an internal error.');
          } else if (data.audit.status === 'Review Required') {
            showNotice(
              'warning',
              'Large or protected sites often block automated scans. This report is conservative—pitch a verified manual audit as the next step.'
            );
          } else if (data.audit.is_mock) {
            showNotice('warning', data.audit.disclaimer || 'This audit uses simulated or demo data.');
          } else {
            showNotice('success', 'Audit report ready for client review.');
          }
        }
      } else {
        if (res.status === 401) {
          handleAuthFailure();
          return;
        }
        showNotice('error', formatFetchError(data, res));
      }
    } catch (e) {
      showNotice('error', 'Network error while generating the audit.');
    }
    setLoading(false);
  };

  const handleToggleLead = (id) => {
    const newSet = new Set(selectedLeads);
    if (newSet.has(id)) newSet.delete(id);
    else newSet.add(id);
    setSelectedLeads(newSet);
  };

  const selectedFilteredCount = filteredLeads.filter((lead) => selectedLeads.has(lead.id)).length;
  const allFilteredSelected = filteredLeads.length > 0 && selectedFilteredCount === filteredLeads.length;

  const toggleSelectAllFiltered = () => {
    const next = new Set(selectedLeads);
    if (allFilteredSelected) {
      filteredLeads.forEach((lead) => next.delete(lead.id));
    } else {
      filteredLeads.forEach((lead) => next.add(lead.id));
    }
    setSelectedLeads(next);
  };

  const resetLeadFilters = () => {
    setLeadSearch('');
    setLeadStatusFilter('all');
    setLeadIntentFilter('all');
  };

  const handleSendEmails = async () => {
    if (selectedLeads.size === 0) return showNotice('error', 'Select leads first!');
    if (!smtpStatus.configured) return showNotice('error', 'SMTP is not configured on the server yet.');
    
    setLoading(true);
    try {
      const res = await fetch(apiUrl('/api/send-bulk'), {
        method: 'POST',
        headers: authHeader,
        body: JSON.stringify({
          subject,
          body,
          lead_ids: Array.from(selectedLeads)
        })
      });
      const data = await parseApiResponse(res);
      if (res.ok) {
        showNotice('success', data.status || 'Campaign launched successfully.');
        fetchAnalytics();
      } else if (res.status === 401) {
        handleAuthFailure();
      } else {
        showNotice('error', formatFetchError(data, res));
      }
    } catch (e) {
      showNotice('error', 'Email trigger failed');
    }
    setLoading(false);
  };

  const handleStatusChange = async (leadId, nextStatus) => {
    try {
      const res = await fetch(apiUrl(`/api/leads/${leadId}/status`), {
        method: 'PATCH',
        headers: authHeader,
        body: JSON.stringify({ status: nextStatus })
      });
      if (res.ok) {
        fetchLeads();
        fetchAnalytics();
      } else {
        const data = await parseApiResponse(res);
        showNotice('error', formatFetchError(data, res));
      }
    } catch (e) {
      showNotice('error', 'Status update failed');
    }
  };

  if (!token) {
    return (
      <div className="app-container" style={{justifyContent: 'center', alignItems: 'center'}}>
        <div className="glass-panel" style={{padding: '3rem', width: '400px', textAlign: 'center'}}>
          <h1 className="logo" style={{fontSize: '2rem', marginBottom: '2rem'}}>SalesBooster AI</h1>
          <h2>{isLogin ? 'Welcome Back' : 'Create Account'}</h2>
          
          <div className="input-group auth-form" style={{flexDirection: 'column', marginTop: '2rem'}}>
            <label htmlFor="auth-username">Username</label>
            <input id="auth-username" type="text" placeholder="Username" value={username} onChange={e => setUsername(e.target.value)} />
            <label htmlFor="auth-password">Password</label>
            <input id="auth-password" type="password" placeholder="Password" value={password} onChange={e => setPassword(e.target.value)} />
            <button onClick={handleAuth} disabled={loading} style={{width: '100%'}}>
              {loading ? 'Processing...' : (isLogin ? 'Login' : 'Sign Up')}
            </button>
            <button className="link-button" style={{marginTop: '1rem'}} onClick={() => setIsLogin(!isLogin)}>
              {isLogin ? "Don't have an account? Sign up" : "Already have an account? Login"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="app-container">
      <aside className="sidebar">
        <div className="logo">🚀 SalesBooster AI</div>
        <nav className="nav-links">
          <button type="button" className={`nav-link ${activeTab === 'keyword' ? 'active' : ''}`} onClick={() => setActiveTab('keyword')} aria-pressed={activeTab === 'keyword'}>
            Keyword Search
          </button>
          <button type="button" className={`nav-link ${activeTab === 'direct' ? 'active' : ''}`} onClick={() => setActiveTab('direct')} aria-pressed={activeTab === 'direct'}>
            Direct URL Scraper
          </button>
          <button type="button" className={`nav-link ${activeTab === 'audit' ? 'active' : ''}`} onClick={() => setActiveTab('audit')} aria-pressed={activeTab === 'audit'}>
            Tech Audit Gen
          </button>
          <button type="button" className={`nav-link ${activeTab === 'leads' ? 'active' : ''}`} onClick={() => setActiveTab('leads')} aria-pressed={activeTab === 'leads'}>
            Lead Manager
          </button>
          <button type="button" className={`nav-link ${activeTab === 'mailer' ? 'active' : ''}`} onClick={() => setActiveTab('mailer')} aria-pressed={activeTab === 'mailer'}>
            Bulk Email Sender
          </button>
        </nav>
        <div style={{marginTop: 'auto'}}>
          <button style={{width: '100%', background: 'transparent', border: '1px solid var(--border-color)', color: 'var(--text-secondary)'}} onClick={handleLogout}>
            Logout
          </button>
        </div>
      </aside>

      <main className="main-content">
        <header className="header animate-fade-in">
          <h1>
            {activeTab === 'keyword' && 'Keyword-Based Intelligence'}
            {activeTab === 'direct' && 'Direct URL Scraper'}
            {activeTab === 'audit' && 'Generate Free Tech Audits'}
            {activeTab === 'leads' && 'Global Lead Database'}
            {activeTab === 'mailer' && 'Automated Campaigns'}
          </h1>
        </header>
        {notice.message && (
          <div className={`notice notice-${notice.type || 'success'}`} role="status">
            {notice.message}
          </div>
        )}

        {activeTab === 'keyword' && (
          <div className="tools-grid animate-fade-in">
            <div className="tool-card glass-panel">
              <h3>Search by Niche & Location</h3>
              <p style={{margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem'}}>
                Example: "cafes in Ahmedabad". We fetch ranked websites, scrape contact data, and auto-save to Lead Manager.
              </p>
              <div className="input-group">
                <input type="text" placeholder="e.g. Optical Shop Ahmedabad" value={keyword} onChange={e => setKeyword(e.target.value)} />
                <button onClick={handleKeywordSearch} disabled={loading}>{loading ? 'Mining Data...' : 'Start Search'}</button>
              </div>
            </div>

            {keywordResult && (
              <div className="tool-card glass-panel" style={{gridColumn: '1 / -1'}}>
                <h3>Keyword Search Results</h3>
                <p style={{margin: 0, color: 'var(--text-secondary)'}}>
                  Keyword: <strong>{keywordResult.keyword}</strong> | New leads found: <strong>{keywordResult.new_leads_found}</strong> | Existing matched leads: <strong>{keywordResult.existing_leads_found || 0}</strong>
                </p>
                <p style={{margin: 0, color: 'var(--text-secondary)'}}>
                  Websites checked: {(keywordResult.searched_urls || []).length}
                </p>
                {!!keywordResult.scrape_failed_urls_count && (
                  <p style={{margin: 0, color: '#fbbf24'}}>
                    Could not scrape {keywordResult.scrape_failed_urls_count} website(s). Try another niche or use Direct URL Scraper.
                  </p>
                )}

                {(keywordResult.new_leads || []).length === 0 ? (
                  <p style={{margin: 0, color: 'var(--text-secondary)'}}>
                    No new contact records were saved from this search. Check Lead Manager for existing matches or try another niche.
                  </p>
                ) : (
                  <div className="table-container" style={{marginTop: '1rem'}}>
                    <table>
                      <thead>
                        <tr>
                          <th>Name/Org</th>
                          <th>Email</th>
                          <th>Phone</th>
                          <th>Intent</th>
                          <th>Score</th>
                          <th>Website</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(keywordResult.new_leads || []).map((lead) => (
                          <tr key={lead.id}>
                            <td>{lead.contact_name || 'Unknown'}</td>
                            <td>{lead.email === 'not_found' ? 'Not found' : lead.email}</td>
                            <td>{lead.phone && lead.phone !== 'not_found' ? lead.phone : 'Not found'}</td>
                            <td>{lead.intent_type || 'awareness'}</td>
                            <td><strong>{lead.lead_score ?? 0}</strong></td>
                            <td>
                              {getLeadWebsite(lead) ? (
                                <a href={getLeadWebsite(lead)} target="_blank" rel="noreferrer" style={{color: 'var(--accent-color)'}}>Open Site</a>
                              ) : 'N/A'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'direct' && (
          <div className="tools-grid animate-fade-in">
            <div className="tool-card glass-panel">
              <h3>Public Site Discovery</h3>
              <p style={{margin: 0, color: 'var(--text-secondary)', fontSize: '0.9rem'}}>
                Checks `robots.txt`, reads sitemap links if available, and scans a few public same-domain pages for visible contact details.
              </p>
              <div className="input-group">
                <input type="text" placeholder="https://example.com/contact" value={targetUrl} onChange={e => setTargetUrl(e.target.value)} />
                <button onClick={handleDirectScrape} disabled={loading}>{loading ? 'Checking Public Pages...' : 'Discover Public Data'}</button>
              </div>
            </div>

            {discoveryResult && (
              <div className="tool-card glass-panel" style={{gridColumn: '1 / -1'}}>
                <h3>Discovery Summary</h3>
                <p style={{margin: 0, color: 'var(--text-secondary)'}}>
                  Robots file: {discoveryResult.robots_found ? 'found' : 'not found'} | Pages scanned: {(discoveryResult.scanned_pages || []).length}
                </p>
                <p style={{margin: 0, color: 'var(--text-secondary)'}}>
                  Sitemaps: {(discoveryResult.sitemaps || []).length} | Disallow rules: {(discoveryResult.disallow_rules || []).length}
                </p>

                <div className="discovery-list">
                  <strong>Scanned Pages</strong>
                  {(discoveryResult.scanned_pages || []).length === 0 ? (
                    <p style={{margin: 0, color: 'var(--text-secondary)'}}>No public pages were scanned.</p>
                  ) : (
                    (discoveryResult.scanned_pages || []).map((page) => (
                      <a key={page} href={page} target="_blank" rel="noreferrer">{page}</a>
                    ))
                  )}
                </div>

                <div className="discovery-list">
                  <strong>Sitemap URLs</strong>
                  {(discoveryResult.sitemap_pages_found || []).length === 0 ? (
                    <p style={{margin: 0, color: 'var(--text-secondary)'}}>No sitemap pages were discovered.</p>
                  ) : (
                    (discoveryResult.sitemap_pages_found || []).map((page) => (
                      <a key={page} href={page} target="_blank" rel="noreferrer">{page}</a>
                    ))
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'audit' && (
          <div className="tools-grid animate-fade-in">
            <div className="tool-card glass-panel" style={{gridColumn: '1 / -1'}}>
              <h3>Client website audit</h3>
              <p style={{color: 'var(--text-secondary)', marginBottom: '1rem', fontSize: '0.9rem'}}>
                Browser-style signals (load, assets, basic SEO/accessibility checks). For enterprise storefronts, expect
                &quot;Review required&quot;—that is intentional so you never pitch false positives. Follow up with a manual pass.
              </p>
              <div className="input-group">
                <input type="text" placeholder="https://client-site.com" value={targetUrl} onChange={e => setTargetUrl(e.target.value)} />
                <button onClick={handleAudit} disabled={loading}>{loading ? 'Analyzing…' : 'Generate audit report'}</button>
              </div>
            </div>

            {audit && (
              <div className="audit-report glass-panel" style={{gridColumn: '1 / -1', marginTop: '1rem'}}>
                <div style={{display: 'flex', flexWrap: 'wrap', gap: '2rem', alignItems: 'center', justifyContent: 'space-between'}}>
                  <div style={{display: 'flex', gap: '2rem', alignItems: 'center'}}>
                    <div className="score-circle">
                      {audit.performance_score}
                    </div>
                    <div>
                      <h2 style={{marginBottom: '0.5rem'}}>Technical audit report</h2>
                      <p style={{color: 'var(--text-secondary)'}}>Generated for {audit.url}</p>
                      <p style={{color: 'var(--text-secondary)', marginTop: '0.35rem'}}>
                        Status:{' '}
                        <span className={`audit-status audit-status-${(audit.status || '').toLowerCase().replace(/\s+/g, '-')}`}>
                          {audit.status}
                        </span>
                      </p>
                      {audit.pages_audited ? (
                        <p style={{color: 'var(--text-secondary)', marginTop: '0.35rem'}}>Pages sampled: {audit.pages_audited}</p>
                      ) : null}
                    </div>
                  </div>
                  <button type="button" className="secondary-button" onClick={copyAuditSummary}>
                    Copy executive summary
                  </button>
                </div>

                {audit.disclaimer && (
                  <div className="audit-disclaimer">
                    {audit.disclaimer}
                  </div>
                )}
                
                <h3 style={{marginTop: '2rem', marginBottom: '1rem'}}>Critical issues</h3>
                <ul className="issue-list">
                  {(audit.critical_issues_found || []).map((issue, idx) => (
                    <li key={idx}>{issue}</li>
                  ))}
                </ul>

                {Array.isArray(audit.technical_observations) && audit.technical_observations.length > 0 && (
                  <div style={{marginTop: '2rem'}}>
                    <h3 style={{marginBottom: '1rem'}}>Additional Technical Observations</h3>
                    <ul className="issue-list">
                      {audit.technical_observations.map((item, idx) => (
                        <li key={`observation-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {Array.isArray(audit.audited_pages) && audit.audited_pages.length > 0 && (
                  <div style={{marginTop: '2rem'}}>
                    <h3 style={{marginBottom: '1rem'}}>Audited Pages</h3>
                    <ul className="issue-list">
                      {audit.audited_pages.map((page, idx) => (
                        <li key={`page-${idx}`}>
                          {page.url} {page.loadEventMs ? `| Load: ${page.loadEventMs}ms` : ''} {page.status ? `| Status: ${page.status}` : ''}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                
                <div style={{background: 'rgba(99, 102, 241, 0.1)', padding: '1rem', borderRadius: '8px', marginTop: '2rem'}}>
                  {audit.estimated_cost_to_fix === '$0' ? (
                    <><strong>Opportunity: </strong> No urgent technical fixes were detected from this automated audit.</>
                  ) : (
                    <><strong>Opportunity: </strong> Our agency can fix these issues for an estimated {audit.estimated_cost_to_fix}.</>
                  )}
                </div>

                {audit.recommendation && (
                  <div style={{marginTop: '1rem', color: 'var(--text-secondary)'}}>
                    <strong style={{color: 'var(--text-primary)'}}>Recommendation:</strong> {audit.recommendation}
                  </div>
                )}

                {Array.isArray(audit.what_we_can_improve) && audit.what_we_can_improve.length > 0 && (
                  <div style={{marginTop: '2rem'}}>
                    <h3 style={{marginBottom: '1rem'}}>What We Can Improve</h3>
                    <ul className="issue-list">
                      {audit.what_we_can_improve.map((item, idx) => (
                        <li key={`improve-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {Array.isArray(audit.competitor_benchmark) && audit.competitor_benchmark.length > 0 && (
                  <div style={{marginTop: '2rem'}}>
                    <h3 style={{marginBottom: '1rem'}}>What Competitors Usually Do Better</h3>
                    <ul className="issue-list">
                      {audit.competitor_benchmark.map((item, idx) => (
                        <li key={`competitor-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {Array.isArray(audit.delivery_plan) && audit.delivery_plan.length > 0 && (
                  <div style={{marginTop: '2rem'}}>
                    <h3 style={{marginBottom: '1rem'}}>What We Will Deliver</h3>
                    <ul className="issue-list">
                      {audit.delivery_plan.map((item, idx) => (
                        <li key={`deliver-${idx}`}>{item}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {audit.outreach_summary && (
                  <div style={{background: 'rgba(16, 185, 129, 0.1)', padding: '1rem', borderRadius: '8px', marginTop: '2rem'}}>
                    <strong>Client Outreach Summary: </strong>{audit.outreach_summary}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {activeTab === 'leads' && (
          <div className="results-area animate-fade-in">
            <div className="tools-grid" style={{ marginBottom: '1rem' }}>
              <div className="tool-card glass-panel">
                <h3 style={{ marginBottom: '0.5rem' }}>Campaign Analytics</h3>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Total Leads: <strong>{analytics.total_leads}</strong></p>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Avg Score: <strong>{analytics.avg_lead_score}</strong></p>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                  Funnel: New {analytics.status_breakdown.new} | Contacted {analytics.status_breakdown.contacted} | Replied {analytics.status_breakdown.replied} | Meeting {analytics.status_breakdown.meeting} | Won {analytics.status_breakdown.won} | Lost {analytics.status_breakdown.lost}
                </p>
              </div>
              <div className="tool-card glass-panel">
                <h3 style={{ marginBottom: '0.5rem' }}>Filtered Snapshot</h3>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Visible rows: <strong>{filteredLeads.length}</strong></p>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>Selected in view: <strong>{selectedFilteredCount}</strong></p>
                <p style={{ margin: 0, color: 'var(--text-secondary)' }}>
                  Avg visible score:{' '}
                  <strong>
                    {filteredLeads.length
                      ? Math.round(
                          filteredLeads.reduce((sum, l) => sum + (Number(l.lead_score) || 0), 0) / filteredLeads.length
                        )
                      : 0}
                  </strong>
                </p>
              </div>
            </div>
            <div className="glass-panel lead-toolbar">
              <input
                ref={csvInputRef}
                type="file"
                accept=".csv,text/csv"
                style={{ display: 'none' }}
                onChange={handleCsvImport}
              />
              <input
                className="custom-input"
                type="text"
                placeholder="Search by name, email, phone, keyword, or URL..."
                value={leadSearch}
                onChange={(e) => setLeadSearch(e.target.value)}
              />
              <select
                className="custom-input lead-filter-select"
                value={leadStatusFilter}
                onChange={(e) => setLeadStatusFilter(e.target.value)}
              >
                <option value="all">All Statuses</option>
                <option value="new">New</option>
                <option value="contacted">Contacted</option>
                <option value="replied">Replied</option>
                <option value="meeting">Meeting</option>
                <option value="won">Won</option>
                <option value="lost">Lost</option>
              </select>
              <select
                className="custom-input lead-filter-select"
                value={leadIntentFilter}
                onChange={(e) => setLeadIntentFilter(e.target.value)}
              >
                <option value="all">All Intents</option>
                <option value="high_intent">High Intent</option>
                <option value="mid_intent">Mid Intent</option>
                <option value="awareness">Awareness</option>
              </select>
              <button type="button" className="secondary-button" onClick={exportLeadsCsv}>
                Export CSV ({filteredLeads.length})
              </button>
              <button type="button" className="secondary-button" onClick={openCsvPicker} disabled={importingCsv}>
                {importingCsv ? 'Importing...' : 'Import CSV'}
              </button>
              <button type="button" className="secondary-button" onClick={downloadCsvTemplate}>
                CSV Template
              </button>
              <button type="button" className="secondary-button" onClick={resetLeadFilters}>
                Reset Filters
              </button>
            </div>
            <div className="table-container glass-panel">
              <table>
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        aria-label="Select all filtered leads"
                        checked={allFilteredSelected}
                        onChange={toggleSelectAllFiltered}
                      />
                    </th>
                    <th>Name/Org</th>
                    <th>Keyword/Source</th>
                    <th>Intent</th>
                    <th>Score</th>
                    <th>Extracted Email</th>
                    <th>Phone</th>
                    <th>Website</th>
                    <th>Status</th>
                    <th>Source Website</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredLeads.length === 0 ? (
                    <tr>
                      <td colSpan="10" style={{ textAlign: 'left', padding: '2rem', color: 'var(--text-secondary)', lineHeight: 1.6 }}>
                        <strong style={{ color: 'var(--text-primary)' }}>
                          {leads.length === 0 ? 'Your lead list is empty for this login.' : 'No rows match current filters.'}
                        </strong>
                        <br />
                        <br />
                        1) Open <strong>Keyword Search</strong>, enter a niche (e.g. &quot;dentist in Austin&quot;), click Start Search—URLs are discovered and a row is stored per site even if email is not public.
                        <br />
                        2) Or use <strong>Direct URL Scraper</strong> with a marketing site URL; if the page is blocked you may still get a placeholder lead plus robots/sitemap discovery.
                        <br />
                        3) For a client demo without scraping, run:{' '}
                        <code style={{ color: 'var(--accent-color)' }}>python manage.py seed_demo_leads --username YOUR_USER</code>
                      </td>
                    </tr>
                  ) : filteredLeads.map((lead) => (
                    <tr key={lead.id}>
                      <td><input type="checkbox" checked={selectedLeads.has(lead.id)} onChange={() => handleToggleLead(lead.id)} /></td>
                      <td>{lead.contact_name || 'Unknown'}</td>
                      <td><span className="tag">{lead.keyword}</span></td>
                      <td>{lead.intent_type || 'awareness'}</td>
                      <td><strong>{lead.lead_score ?? 0}</strong></td>
                      <td><strong>{lead.email === 'not_found' ? 'Not found' : lead.email}</strong></td>
                      <td>{lead.phone && lead.phone !== 'not_found' ? lead.phone : 'N/A'}</td>
                      <td>{getLeadWebsite(lead) ? 'Available' : 'Not found'}</td>
                      <td>
                        <select
                          className="custom-input"
                          value={lead.status || 'new'}
                          onChange={(e) => handleStatusChange(lead.id, e.target.value)}
                        >
                          <option value="new">New</option>
                          <option value="contacted">Contacted</option>
                          <option value="replied">Replied</option>
                          <option value="meeting">Meeting</option>
                          <option value="won">Won</option>
                          <option value="lost">Lost</option>
                        </select>
                      </td>
                      <td>
                        {getLeadWebsite(lead) ? (
                          <a href={getLeadWebsite(lead)} target="_blank" rel="noreferrer" style={{color: 'var(--accent-color)'}}>Open Site</a>
                        ) : 'N/A'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div style={{marginTop: '1.5rem', display: 'flex', gap: '1rem'}}>
              <button onClick={() => setActiveTab('mailer')} disabled={selectedLeads.size === 0}>Send Email to Selected ({selectedLeads.size})</button>
            </div>
          </div>
        )}

        {activeTab === 'mailer' && (
          <div className="tools-grid animate-fade-in">
            <div className="tool-card glass-panel" style={{gridColumn: '1 / -1'}}>
              <h3>Prepare Outreach</h3>
              <p style={{color: 'var(--text-secondary)', marginBottom: '1rem'}}>
                Configure your SMTP and launch your campaign to {selectedLeads.size} selected leads.
              </p>
              <div className="glass-panel" style={{padding: '1rem', marginBottom: '1rem', background: 'rgba(255,255,255,0.03)'}}>
                <p style={{margin: 0, color: smtpStatus.configured ? 'var(--success-color)' : '#f59e0b'}}>
                  {smtpStatus.configured
                    ? `Server SMTP ready: ${smtpStatus.sender || 'configured'} via ${smtpStatus.host}:${smtpStatus.port}`
                    : 'Server SMTP not configured yet. Ask admin to set SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS.'}
                </p>
              </div>
              <input className="custom-input" style={{marginBottom: '1rem', width: '100%'}} type="text" placeholder="Subject Line" value={subject} onChange={e => setSubject(e.target.value)} />
              <textarea className="custom-input" style={{minHeight: '200px', marginBottom: '1rem', width: '100%', resize: 'vertical'}} value={body} onChange={e => setBody(e.target.value)} />
              <button style={{background: 'var(--success-color)'}} onClick={handleSendEmails} disabled={loading || selectedLeads.size === 0 || !smtpStatus.configured}>
                {loading ? 'Sending Emails & Logging...' : `Launch Campaign to ${selectedLeads.size} Leads`}
              </button>
            </div>
          </div>
        )}

      </main>
    </div>
  );
}

export default App;
