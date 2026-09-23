"""按业务模块拆分的数据模型；本文件统一导出，保持 `from app.models import X` 的写法不变。"""

from __future__ import annotations

from app.models._base import ForeignKey, ForeignKeyConstraint, uuid_pk
from app.models.system import AuditLog, BackgroundJob, ImportBatch, LoginSession, Notification, RealtimeEvent, RoleMenuPermission, User
from app.models.members import ClassJoinRequest, ClassMember, TeachingClass, Team, TeamMember, TeamRequest, Topic
from app.models.materials import TeachingMaterial, TeachingMaterialAsset, TeachingMaterialFolder
from app.models.assignments import Assignment, FileObject, FileObjectAsset, MarkdownAsset, Submission, SubmissionAnnotation, SubmissionAssessment, SubmissionDocument, SubmissionDocumentAsset, SubmissionVersion, SubmissionWorkspace, VersionFile
from app.models.reviews import PeerReview, ReviewAssignment, ReviewCampaign
from app.models.grades import Grade, GradeCoefficient, GradeRevision
from app.models.capstone import CAPSTONE_STAGES, CapstoneAsset, CapstoneConfig, CapstoneDocument, CapstoneDocumentTemplate, CapstoneModuleAssignment, CapstoneStageGrade, CapstoneUnlock
from app.models.attendance import AttendanceScoreManual

__all__ = [
    "Assignment",
    "AttendanceScoreManual",
    "AuditLog",
    "BackgroundJob",
    "CAPSTONE_STAGES",
    "CapstoneAsset",
    "CapstoneConfig",
    "CapstoneDocument",
    "CapstoneDocumentTemplate",
    "CapstoneModuleAssignment",
    "CapstoneStageGrade",
    "CapstoneUnlock",
    "ClassJoinRequest",
    "ClassMember",
    "FileObject",
    "FileObjectAsset",
    "ForeignKey",
    "ForeignKeyConstraint",
    "Grade",
    "GradeCoefficient",
    "GradeRevision",
    "ImportBatch",
    "LoginSession",
    "MarkdownAsset",
    "Notification",
    "PeerReview",
    "RealtimeEvent",
    "ReviewAssignment",
    "ReviewCampaign",
    "RoleMenuPermission",
    "Submission",
    "SubmissionAnnotation",
    "SubmissionAssessment",
    "SubmissionDocument",
    "SubmissionDocumentAsset",
    "SubmissionVersion",
    "SubmissionWorkspace",
    "TeachingClass",
    "TeachingMaterial",
    "TeachingMaterialAsset",
    "TeachingMaterialFolder",
    "Team",
    "TeamMember",
    "TeamRequest",
    "Topic",
    "User",
    "VersionFile",
    "uuid_pk",
]
