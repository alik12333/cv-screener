"""
Shared Pydantic schema for the candidate profile.

Both generate_cvs.py and extract.py must agree on this exact shape: generation
writes the ground truth from it, extraction is graded against that same ground
truth. If the two files each defined their own version, they could silently
drift apart and the eval would be comparing against the wrong contract.
"""

from typing import List

from pydantic import BaseModel, Field


class Employment(BaseModel):
    employer: str
    title: str
    start: str = Field(description="Month and year, e.g. 'March 2019'")
    end: str = Field(description="Month and year, or 'Present'")
    bullets: List[str] = Field(description="2-4 achievement lines")


class Education(BaseModel):
    institution: str
    qualification: str
    year: str


class CandidateProfile(BaseModel):
    full_name: str
    email: str
    phone: str
    location: str = Field(description="UK city")
    right_to_work: bool
    personal_statement: str = Field(description="2-3 sentences, first person")
    total_years_experience: int
    current_title: str
    skills: List[str]
    employment: List[Employment] = Field(description="Most recent first, 2-4 roles")
    education: List[Education]
    notice_period: str
    salary_expectation: str
