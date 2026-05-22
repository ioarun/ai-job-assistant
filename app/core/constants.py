# Prompt templates and constants

SKILL_GAP_ANALYSIS_PROMPT = """
You are an expert career coach analyzing a resume against a job description.

Resume:
{resume_text}

Job Description:
{job_text}

Provide a detailed skill gap analysis including:
1. Missing technical skills
2. Missing soft skills
3. Experience gaps
4. Recommended projects to build
5. Certification recommendations

Format as structured JSON.
"""

COVER_LETTER_PROMPT = """
You are an expert cover letter writer.

Resume:
{resume_text}

Job Description:
{job_text}

Write a compelling, personalized cover letter (3-4 paragraphs) that:
1. Shows enthusiasm for the role
2. Highlights relevant experience
3. Addresses key requirements from the job description
4. Ends with a strong call to action
"""

INTERVIEW_PREP_PROMPT = """
You are an expert interview coach.

Job Title: {job_title}
Job Description:
{job_text}

Resume:
{resume_text}

Generate 10 specific interview questions likely to be asked for this role, including:
- 3 technical questions
- 3 behavioral questions
- 2 situational questions
- 2 questions about the company/role fit

For each question, provide a brief hint for a strong answer.
"""
