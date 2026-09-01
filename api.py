from fastapi import FastAPI
from server import search_employees

app = FastAPI()


@app.get("/employees")
def get_employees(
    department: str = "",
    nationality: str = "",
    skill: str = ""
):
    employees = search_employees(
        department=department,
        nationality=nationality,
        skill=skill
    )

    return {
        "conditions": {
            "department": department,
            "nationality": nationality,
            "skill": skill
        },
        "count": len(employees),
        "employees": employees
    }