from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Grade, GradeCoefficient, PeerReview, ReviewAssignment, ReviewCampaign


TWO_PLACES = Decimal("0.01")
MAX_SCORE = Decimal("100.00")


def final_score(peer_score: Decimal | float, coefficient: Decimal | float) -> Decimal:
    value = Decimal(str(peer_score)) * Decimal(str(coefficient))
    return min(value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP), MAX_SCORE)


def finalize_campaign(db: Session, campaign: ReviewCampaign, generated_at: datetime | None = None) -> None:
    if campaign.grades_generated_at is not None:
        return
    generated_at = generated_at or datetime.now(UTC)
    allocations = db.scalars(
        select(ReviewAssignment)
        .where(ReviewAssignment.campaign_id == campaign.id)
        .order_by(ReviewAssignment.created_at)
        .with_for_update()
    ).all()
    team_ids = {item.participant_team_id for item in allocations if item.participant_team_id}
    coefficients = {
        item.team_id: item
        for item in db.scalars(
            select(GradeCoefficient).where(
                GradeCoefficient.assignment_id == campaign.assignment_id,
                GradeCoefficient.team_id.in_(team_ids),
            )
        ).all()
    } if team_ids else {}
    for team_id in team_ids - set(coefficients):
        item = GradeCoefficient(assignment_id=campaign.assignment_id, team_id=team_id)
        db.add(item)
        coefficients[team_id] = item
    db.flush()

    for allocation in allocations:
        existing = db.scalar(
            select(Grade).where(
                Grade.assignment_id == campaign.assignment_id,
                Grade.subject_user_id == allocation.reviewer_id,
            )
        )
        if existing:
            continue
        review = db.scalar(
            select(PeerReview).where(
                PeerReview.campaign_id == campaign.id,
                PeerReview.reviewee_id == allocation.reviewer_id,
                PeerReview.status == "VALID",
            )
        )
        peer_score = Decimal(str(review.total_score)).quantize(TWO_PLACES) if review else None
        coefficient = coefficients.get(allocation.participant_team_id)
        draft_score = final_score(peer_score, coefficient.draft_value) if peer_score is not None and coefficient and coefficient.draft_value is not None else None
        db.add(
            Grade(
                assignment_id=campaign.assignment_id,
                campaign_id=campaign.id,
                subject_user_id=allocation.reviewer_id,
                coefficient_id=coefficient.id if coefficient else None,
                peer_review_id=review.id if review else None,
                peer_score=peer_score,
                draft_score=draft_score,
                status="DRAFT" if draft_score is not None else "PENDING",
            )
        )
    campaign.status = "CLOSED"
    campaign.grades_generated_at = generated_at
    campaign.version += 1
