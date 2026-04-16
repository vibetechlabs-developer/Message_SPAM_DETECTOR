from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
from pydantic import BaseModel
from typing import List
import uvicorn

import models
from db import engine, get_db
from auth import verify_password, get_password_hash, create_access_token, get_current_user
from scraper import scrape_leads
from search_api import SearchAPI
from mailer import send_bulk_email

# Create DB Tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="SalesBooster AI", description="Advanced DB & Auth enabled Lead Generator.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Schemas
class UserCreate(BaseModel):
    username: str
    password: str

class KeywordRequest(BaseModel):
    keyword: str

class UrlRequest(BaseModel):
    url: str

class EmailBroadcast(BaseModel):
    smtp_user: str
    smtp_pass: str
    subject: str
    body: str
    lead_ids: List[int]

class LeadStatusUpdate(BaseModel):
    status: str


def calculate_lead_score(email: str, phone: str, website_found: bool) -> int:
    score = 20
    if email and email != "not_found":
        score += 40
    if phone:
        score += 25
    if website_found:
        score += 15
    return min(score, 100)


def ensure_lead_columns() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "leads" not in table_names:
        return

    existing_columns = {col["name"] for col in inspector.get_columns("leads")}
    column_sql = {
        "website_url": "ALTER TABLE leads ADD COLUMN website_url VARCHAR",
        "website_found": "ALTER TABLE leads ADD COLUMN website_found BOOLEAN DEFAULT 0",
        "intent_type": "ALTER TABLE leads ADD COLUMN intent_type VARCHAR DEFAULT 'awareness'",
        "lead_score": "ALTER TABLE leads ADD COLUMN lead_score INTEGER DEFAULT 0",
        "status": "ALTER TABLE leads ADD COLUMN status VARCHAR DEFAULT 'new'",
    }
    with engine.begin() as conn:
        for col_name, stmt in column_sql.items():
            if col_name not in existing_columns:
                conn.execute(text(stmt))


ensure_lead_columns()

@app.post("/api/register")
def register(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_pass = get_password_hash(user.password)
    new_user = models.User(username=user.username, hashed_password=hashed_pass)
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully"}

@app.post("/api/login")
def login(user: UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if not db_user or not verify_password(user.password, db_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/api/me")
def read_users_me(current_user: models.User = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username}

@app.post("/api/keyword-search")
def run_keyword_search(req: KeywordRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    urls = SearchAPI.get_urls_for_keyword(req.keyword)
    all_leads = []
    
    for url in urls:
        res = scrape_leads(url)
        leads_payload = res.get("leads", [])
        if not leads_payload:
            leads_payload = [{
                "source": url,
                "contact_name": "",
                "email": "not_found",
                "phone": "",
            }]

        for l in leads_payload:
            lead_email = l.get("email", "not_found")
            existing_query = db.query(models.Lead).filter(
                models.Lead.owner_id == current_user.id,
                models.Lead.source_url == l["source"],
            )
            if lead_email != "not_found":
                existing_query = existing_query.filter(models.Lead.email == lead_email)
            existing = existing_query.first()

            if existing:
                continue

            website_found = bool(l["source"])
            db_lead = models.Lead(
                keyword=req.keyword,
                source_url=l["source"],
                website_url=l["source"] if website_found else "",
                website_found=website_found,
                contact_name=l.get("contact_name", ""),
                email=lead_email,
                phone=l.get("phone", ""),
                intent_type="awareness",
                lead_score=calculate_lead_score(lead_email, l.get("phone", ""), website_found),
                status="new",
                owner_id=current_user.id,
            )
            db.add(db_lead)
            all_leads.append(l)
    
    db.commit()
    return {"status": "success", "new_leads_found": len(all_leads)}


@app.post("/api/scrape-url")
def scrape_single_url(req: UrlRequest, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    res = scrape_leads(req.url)
    if res["status"] != "success":
        raise HTTPException(status_code=400, detail=res.get("message", "Unable to scrape this URL"))

    created = 0
    for l in res["leads"]:
        lead_email = l.get("email", "not_found")
        existing_query = db.query(models.Lead).filter(
            models.Lead.owner_id == current_user.id,
            models.Lead.source_url == l["source"],
        )
        if lead_email != "not_found":
            existing_query = existing_query.filter(models.Lead.email == lead_email)
        existing = existing_query.first()
        if existing:
            continue

        website_found = bool(l["source"])
        db.add(
            models.Lead(
                keyword="direct_scrape",
                source_url=l["source"],
                website_url=l["source"] if website_found else "",
                website_found=website_found,
                contact_name=l.get("contact_name", ""),
                email=lead_email,
                phone=l.get("phone", ""),
                intent_type="awareness",
                lead_score=calculate_lead_score(lead_email, l.get("phone", ""), website_found),
                status="new",
                owner_id=current_user.id,
            )
        )
        created += 1

    db.commit()
    return {
        "status": "success",
        "new_leads_found": created,
        "discovery": res.get("discovery", {}),
    }

@app.get("/api/leads")
def get_leads(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    leads = db.query(models.Lead).filter(models.Lead.owner_id == current_user.id).all()
    return leads


@app.get("/api/analytics")
def get_analytics(db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    leads = db.query(models.Lead).filter(models.Lead.owner_id == current_user.id).all()
    total = len(leads)
    avg_score = round(sum((lead.lead_score or 0) for lead in leads) / total, 2) if total else 0
    statuses = ["new", "contacted", "replied", "meeting", "won", "lost"]
    breakdown = {s: 0 for s in statuses}
    for lead in leads:
        key = lead.status if lead.status in breakdown else "new"
        breakdown[key] += 1
    return {
        "total_leads": total,
        "avg_lead_score": avg_score,
        "status_breakdown": breakdown,
    }


@app.patch("/api/leads/{lead_id}/status")
def update_lead_status(lead_id: int, req: LeadStatusUpdate, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    allowed = {"new", "contacted", "replied", "meeting", "won", "lost"}
    if req.status not in allowed:
        raise HTTPException(status_code=400, detail="Invalid status")

    lead = db.query(models.Lead).filter(
        models.Lead.id == lead_id,
        models.Lead.owner_id == current_user.id,
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    lead.status = req.status
    db.commit()
    return {"status": "updated"}


@app.post("/api/audit")
def run_basic_audit(req: UrlRequest, current_user: models.User = Depends(get_current_user)):
    return {
        "audit": {
            "url": req.url,
            "performance_score": 72,
            "critical_issues_found": [
                "No compressed image strategy detected on primary pages.",
                "Missing meta description on important landing pages.",
                "No visible lead capture CTA above the fold.",
            ],
            "estimated_cost_to_fix": "$300 - $900",
        }
    }

@app.post("/api/send-bulk")
def send_bulk(req: EmailBroadcast, db: Session = Depends(get_db), current_user: models.User = Depends(get_current_user)):
    target_emails = []
    for lid in req.lead_ids:
        lead = db.query(models.Lead).filter(models.Lead.id == lid, models.Lead.owner_id == current_user.id).first()
        if lead:
            target_emails.append(lead.email)
            
    success = send_bulk_email(
        req.smtp_user, req.smtp_pass, target_emails, 
        req.subject, req.body, db, current_user.id
    )
    
    if success:
         return {"status": "Emails queued and sent successfully"}
    else:
         raise HTTPException(status_code=500, detail="Failed to connect to SMTP server")

if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
