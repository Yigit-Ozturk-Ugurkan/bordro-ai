from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="Europe/Istanbul",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    users = relationship("User", back_populates="organization")
    employees = relationship("Employee", back_populates="organization")
