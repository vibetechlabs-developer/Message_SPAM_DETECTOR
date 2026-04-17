import { chromium } from 'playwright';

const targetUrl = process.argv[2];

if (!targetUrl) {
  console.error('Missing target URL');
  process.exit(1);
}

const challengeMarkers = [
  'captcha',
  'robot check',
  'verify you are human',
  'access denied',
  'request blocked',
  'automated access',
  'security challenge',
  'validatecaptcha',
];

const preferredPathKeywords = ['contact', 'about', 'service', 'services', 'pricing', 'product', 'solutions'];

function looksBlocked(text) {
  const haystack = String(text || '').toLowerCase();
  return challengeMarkers.some((marker) => haystack.includes(marker));
}

function average(values) {
  const valid = values.filter((value) => typeof value === 'number' && Number.isFinite(value));
  if (!valid.length) return null;
  return Math.round(valid.reduce((sum, value) => sum + value, 0) / valid.length);
}

function maxValue(values) {
  const valid = values.filter((value) => typeof value === 'number' && Number.isFinite(value));
  return valid.length ? Math.max(...valid) : 0;
}

function sum(values) {
  return values.filter((value) => typeof value === 'number' && Number.isFinite(value)).reduce((a, b) => a + b, 0);
}

function pickImportantLinks(pageUrl, discoveredLinks) {
  const deduped = [...new Set(discoveredLinks)].filter(Boolean);
  const current = new URL(pageUrl);
  const scored = deduped
    .map((href) => {
      try {
        const parsed = new URL(href);
        let score = 0;
        if (parsed.origin !== current.origin) return null;
        const path = parsed.pathname.toLowerCase();
        if (path === '/' || path === current.pathname.toLowerCase()) score -= 10;
        for (const keyword of preferredPathKeywords) {
          if (path.includes(keyword)) score += 10;
        }
        if (path.split('/').filter(Boolean).length <= 2) score += 3;
        return { href: parsed.toString(), score };
      } catch {
        return null;
      }
    })
    .filter(Boolean)
    .sort((a, b) => b.score - a.score);

  return scored.slice(0, 3).map((item) => item.href);
}

async function collectPageMetrics(page) {
  return page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0];
    const resources = performance.getEntriesByType('resource');
    const canonical = document.querySelector('link[rel="canonical"]')?.getAttribute('href') || '';
    const robots = document.querySelector('meta[name="robots"]')?.getAttribute('content') || '';
    const title = document.title || '';
    const description =
      document.querySelector('meta[name="description"]')?.getAttribute('content') ||
      document.querySelector('meta[property="og:description"]')?.getAttribute('content') ||
      document.querySelector('meta[name="twitter:description"]')?.getAttribute('content') ||
      '';
    const viewport = document.querySelector('meta[name="viewport"]')?.getAttribute('content') || '';
    const htmlLang = document.documentElement?.getAttribute('lang') || '';
    const bodyText = document.body?.innerText?.slice(0, 4000) || '';
    const images = Array.from(document.images || []);
    const forms = Array.from(document.querySelectorAll('form'));
    const inputs = Array.from(document.querySelectorAll('input, textarea, select'));
    const links = Array.from(document.querySelectorAll('a[href]'));
    const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"]'));
    const origin = window.location.origin;
    const internalLinks = links
      .map((link) => link.getAttribute('href'))
      .map((href) => {
        try {
          return new URL(href, window.location.href).toString();
        } catch {
          return '';
        }
      })
      .filter((href) => href.startsWith(origin));

    const missingAltCount = images.filter((img) => !img.getAttribute('alt')?.trim()).length;
    const oversizedImages = images.filter((img) => {
      const width = Number(img.naturalWidth || img.width || 0);
      const height = Number(img.naturalHeight || img.height || 0);
      return width * height > 2_000_000;
    }).length;

    const unlabeledInputsCount = inputs.filter((input) => {
      const id = input.getAttribute('id');
      const ariaLabel = input.getAttribute('aria-label');
      const ariaLabelledBy = input.getAttribute('aria-labelledby');
      const placeholder = input.getAttribute('placeholder');
      const label = id ? document.querySelector(`label[for="${id}"]`) : null;
      return !label && !ariaLabel && !ariaLabelledBy && !placeholder;
    }).length;

    const emptyButtonsCount = buttons.filter((button) => {
      const text = button.innerText || button.getAttribute('value') || '';
      const ariaLabel = button.getAttribute('aria-label') || '';
      return !(text.trim() || ariaLabel.trim());
    }).length;

    const internalLinkCount = internalLinks.length;
    const externalLinkCount = links.length - internalLinkCount;
    const insecureRequests = resources.filter((entry) => entry.name.startsWith('http://')).length;
    const thirdPartyDomains = new Set(
      resources
        .map((entry) => {
          try {
            return new URL(entry.name).hostname;
          } catch {
            return '';
          }
        })
        .filter((hostname) => hostname && !hostname.endsWith(window.location.hostname))
    ).size;

    return {
      title,
      titleLength: title.trim().length,
      metaDescriptionLength: description.trim().length,
      hasMetaDescription: Boolean(description.trim()),
      hasViewport: Boolean(viewport.trim()),
      hasCanonical: Boolean(canonical.trim()),
      hasNoindex: /noindex/i.test(robots),
      htmlLang,
      h1Count: document.querySelectorAll('h1').length,
      formsCount: forms.length,
      inputsCount: inputs.length,
      unlabeledInputsCount,
      buttonsCount: buttons.length,
      emptyButtonsCount,
      imageCount: images.length,
      missingAltCount,
      oversizedImages,
      internalLinkCount,
      externalLinkCount,
      insecureRequests,
      thirdPartyDomains,
      domContentLoadedMs: nav ? Math.round(nav.domContentLoadedEventEnd) : null,
      loadEventMs: nav ? Math.round(nav.loadEventEnd) : null,
      totalRequests: resources.length,
      scriptRequests: resources.filter((entry) => entry.initiatorType === 'script').length,
      imageRequests: resources.filter((entry) => entry.initiatorType === 'img').length,
      stylesheetRequests: resources.filter((entry) => entry.initiatorType === 'link').length,
      totalTransferSize: Math.round(
        resources.reduce((sum, entry) => sum + (entry.transferSize || 0), 0) + (nav?.transferSize || 0)
      ),
      bodyText,
      internalLinks: internalLinks.slice(0, 80),
    };
  });
}

async function auditPage(context, pageUrl) {
  const page = await context.newPage();
  const failedRequests = [];
  const badResponses = [];
  const consoleErrors = [];

  page.on('requestfailed', (request) => {
    failedRequests.push({
      url: request.url(),
      errorText: request.failure()?.errorText || 'Request failed',
      resourceType: request.resourceType(),
    });
  });

  page.on('response', (response) => {
    const status = response.status();
    if (status >= 400) {
      badResponses.push({
        url: response.url(),
        status,
        resourceType: response.request().resourceType(),
      });
    }
  });

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text());
    }
  });

  try {
    // `networkidle` rarely completes on large SPAs (analytics, websockets). Prefer DOM-ready + short settle.
    const response = await page.goto(pageUrl, {
      waitUntil: 'domcontentloaded',
      timeout: 55000,
    });
    await page.waitForLoadState('load', { timeout: 20000 }).catch(() => {});
    await page.evaluate(() => new Promise((r) => setTimeout(r, 900)));

    const metrics = await collectPageMetrics(page);
    const finalUrl = page.url();
    return {
      url: finalUrl,
      status: response?.status() ?? null,
      title: metrics.title,
      titleLength: metrics.titleLength,
      metaDescriptionLength: metrics.metaDescriptionLength,
      hasMetaDescription: metrics.hasMetaDescription,
      hasViewport: metrics.hasViewport,
      hasCanonical: metrics.hasCanonical,
      hasNoindex: metrics.hasNoindex,
      htmlLang: metrics.htmlLang,
      h1Count: metrics.h1Count,
      formsCount: metrics.formsCount,
      inputsCount: metrics.inputsCount,
      unlabeledInputsCount: metrics.unlabeledInputsCount,
      buttonsCount: metrics.buttonsCount,
      emptyButtonsCount: metrics.emptyButtonsCount,
      imageCount: metrics.imageCount,
      missingAltCount: metrics.missingAltCount,
      oversizedImages: metrics.oversizedImages,
      internalLinkCount: metrics.internalLinkCount,
      externalLinkCount: metrics.externalLinkCount,
      insecureRequests: metrics.insecureRequests,
      thirdPartyDomains: metrics.thirdPartyDomains,
      domContentLoadedMs: metrics.domContentLoadedMs,
      loadEventMs: metrics.loadEventMs,
      totalRequests: metrics.totalRequests,
      scriptRequests: metrics.scriptRequests,
      imageRequests: metrics.imageRequests,
      stylesheetRequests: metrics.stylesheetRequests,
      totalTransferSize: metrics.totalTransferSize,
      failedRequestCount: failedRequests.length,
      badResponseCount: badResponses.length,
      consoleErrorCount: consoleErrors.length,
      blocked: looksBlocked(`${finalUrl} ${metrics.title} ${metrics.bodyText}`),
      internalLinks: metrics.internalLinks,
    };
  } finally {
    await page.close();
  }
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  userAgent:
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
});

function blockedPayload(reason) {
  return {
    status: null,
    finalUrl: targetUrl,
    title: '',
    hasMetaDescription: false,
    hasViewport: false,
    htmlLang: '',
    h1Count: 0,
    formsCount: 0,
    inputsCount: 0,
    unlabeledInputsCount: 0,
    buttonsCount: 0,
    emptyButtonsCount: 0,
    imageCount: 0,
    missingAltCount: 0,
    oversizedImages: 0,
    internalLinkCount: 0,
    externalLinkCount: 0,
    insecureRequests: 0,
    thirdPartyDomains: 0,
    titleLength: 0,
    metaDescriptionLength: 0,
    hasCanonical: false,
    hasNoindex: false,
    domContentLoadedMs: null,
    loadEventMs: null,
    totalRequests: 0,
    scriptRequests: 0,
    imageRequests: 0,
    stylesheetRequests: 0,
    totalTransferSize: 0,
    failedRequestCount: 0,
    badResponseCount: 0,
    consoleErrorCount: 0,
    blocked: true,
    pagesAudited: 1,
    pageSummaries: [{ url: targetUrl, status: null, title: '', blocked: true }],
    blockedReason: reason || 'navigation_or_timeout',
  };
}

try {
  const homepage = await auditPage(context, targetUrl);

  const linksToAudit = homepage.blocked ? [] : pickImportantLinks(homepage.url, homepage.internalLinks || []);
  const pages = [homepage];

  for (const link of linksToAudit) {
    if (pages.some((page) => page.url === link)) continue;
    try {
      pages.push(await auditPage(context, link));
    } catch {
      // ignore individual subpage failures and keep the overall audit usable
    }
  }

  const result = {
    status: homepage.status,
    finalUrl: homepage.url,
    title: homepage.title,
    hasMetaDescription: homepage.hasMetaDescription,
    hasViewport: homepage.hasViewport,
    htmlLang: homepage.htmlLang,
    h1Count: homepage.h1Count,
    formsCount: maxValue(pages.map((page) => page.formsCount)),
    inputsCount: maxValue(pages.map((page) => page.inputsCount)),
    unlabeledInputsCount: sum(pages.map((page) => page.unlabeledInputsCount)),
    buttonsCount: maxValue(pages.map((page) => page.buttonsCount)),
    emptyButtonsCount: sum(pages.map((page) => page.emptyButtonsCount)),
    imageCount: maxValue(pages.map((page) => page.imageCount)),
    missingAltCount: sum(pages.map((page) => page.missingAltCount)),
    oversizedImages: sum(pages.map((page) => page.oversizedImages)),
    internalLinkCount: homepage.internalLinkCount,
    externalLinkCount: homepage.externalLinkCount,
    insecureRequests: sum(pages.map((page) => page.insecureRequests)),
    thirdPartyDomains: maxValue(pages.map((page) => page.thirdPartyDomains)),
    titleLength: homepage.titleLength,
    metaDescriptionLength: homepage.metaDescriptionLength,
    hasCanonical: pages.every((page) => page.hasCanonical),
    hasNoindex: pages.some((page) => page.hasNoindex),
    domContentLoadedMs: average(pages.map((page) => page.domContentLoadedMs)),
    loadEventMs: average(pages.map((page) => page.loadEventMs)),
    totalRequests: sum(pages.map((page) => page.totalRequests)),
    scriptRequests: sum(pages.map((page) => page.scriptRequests)),
    imageRequests: sum(pages.map((page) => page.imageRequests)),
    stylesheetRequests: sum(pages.map((page) => page.stylesheetRequests)),
    totalTransferSize: sum(pages.map((page) => page.totalTransferSize)),
    failedRequestCount: sum(pages.map((page) => page.failedRequestCount)),
    badResponseCount: sum(pages.map((page) => page.badResponseCount)),
    consoleErrorCount: sum(pages.map((page) => page.consoleErrorCount)),
    blocked: pages.some((page) => page.blocked),
    pagesAudited: pages.length,
    pageSummaries: pages.map((page) => ({
      url: page.url,
      status: page.status,
      title: page.title,
      loadEventMs: page.loadEventMs,
      domContentLoadedMs: page.domContentLoadedMs,
      totalRequests: page.totalRequests,
      totalTransferSize: page.totalTransferSize,
      failedRequestCount: page.failedRequestCount,
      badResponseCount: page.badResponseCount,
      consoleErrorCount: page.consoleErrorCount,
      blocked: page.blocked,
    })),
  };

  console.log(JSON.stringify(result));
} catch (error) {
  console.log(JSON.stringify(blockedPayload(error instanceof Error ? error.message : String(error))));
  process.exit(0);
} finally {
  await context.close();
  await browser.close();
}
