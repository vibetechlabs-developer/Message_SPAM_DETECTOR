from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, Text
from db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)

class Lead(Base):
    __tablename__ = "leads"
    id = Column(Integer, primary_key=True, index=True)
    keyword = Column(String, index=True)
    source_url = Column(String)
    website_url = Column(String, nullable=True)
    website_found = Column(Boolean, default=False)
    contact_name = Column(String, nullable=True)
    email = Column(String)
    phone = Column(String, nullable=True)
    intent_type = Column(String, default="awareness")
    lead_score = Column(Integer, default=0)
    status = Column(String, default="new")
    owner_id = Column(Integer, ForeignKey("users.id"))

class EmailLog(Base):
    __tablename__ = "email_logs"
    id = Column(Integer, primary_key=True, index=True)
    target_email = Column(String)
    subject = Column(String)
    status = Column(String) # success or failed
    error_msg = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"))
