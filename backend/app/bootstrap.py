from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def main() -> None:
    with SessionLocal.begin() as session:
        teacher = session.scalar(select(User).where(User.login_name == "teacher"))
        if not teacher:
            session.add(User(login_name="teacher", display_name="老师", password_hash=hash_password("123456"), role="TEACHER"))
        elif teacher.display_name == "王老师":
            teacher.display_name = "老师"


if __name__ == "__main__":
    main()
