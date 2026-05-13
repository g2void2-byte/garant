"""Helpers operating on the new TMA tables.

The original ``DB`` class lives in ``utils.database.db`` and concerns the
legacy bot logic. We add a thin namespace here so the FastAPI backend can
import ``WebDB`` without touching the existing class. All methods are sync
peewee calls that should be awaited via ``asyncio.to_thread`` from async
contexts.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from peewee import JOIN, fn

from utils.database.models import (
    Category,
    Deals,
    Deposit,
    Invoices,
    Notification,
    OnlineStatus,
    ProfileExtra,
    Review,
    Service,
    Users,
)
from routers.utils.status_deals import SUCCESS


DEFAULT_CATEGORIES = [
    ("airline-hotels", "Авиа и отели", "plane"),
    ("crypto-accounts", "Аккаунты криптобирж и ЭПС", "bitcoin"),
    ("anonymity", "Анонимность и безопасность", "shield"),
    ("bruteforce", "Брутфорс", "key"),
    ("verification", "Верификация", "badge-check"),
    ("hacking", "Взлом", "skull"),
    ("visas", "Визы/шенген", "stamp"),
    ("debit-cards", "Дебетовые карты", "credit-card"),
    ("design", "Дизайн", "palette"),
    ("documents", "Изготовление документов", "file-text"),
    ("stamps", "Изготовление печатей и штампов", "stamp"),
    ("copywriting", "Копирайтинг", "edit"),
    ("loans", "Кредиты", "banknote"),
    ("exchangers", "Обменники", "arrow-left-right"),
    ("cashout", "Обнал сервисы", "wallet"),
    ("other", "Прочее", "more-horizontal"),
]


class WebDB:
    """Methods used by the FastAPI layer."""

    # ----- categories ------------------------------------------------

    def seed_default_categories(self) -> None:
        for idx, (slug, name, icon_key) in enumerate(DEFAULT_CATEGORIES):
            Category.get_or_create(
                slug=slug,
                defaults={"name": name, "icon_key": icon_key, "sort_order": idx},
            )

    def list_categories(self) -> list[dict]:
        rows = (
            Category.select(
                Category,
                fn.COUNT(Service.id).alias("services_count"),
            )
            .join(Service, JOIN.LEFT_OUTER)
            .where(Category.is_active == True)  # noqa: E712
            .group_by(Category.id)
            .order_by(Category.sort_order, Category.name)
        )
        return [
            {
                "id": row.id,
                "slug": row.slug,
                "name": row.name,
                "icon_key": row.icon_key,
                "services_count": getattr(row, "services_count", 0) or 0,
            }
            for row in rows
        ]

    # ----- services --------------------------------------------------

    def list_services(
        self,
        category_slug: str | None = None,
        q: str | None = None,
        owner_username: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict]:
        query = (
            Service.select(Service, Category)
            .join(Category)
            .where(Service.status == "active")
            .order_by(Service.created_at.desc())
        )
        if category_slug:
            query = query.where(Category.slug == category_slug)
        if owner_username:
            query = query.where(Service.owner_username == owner_username.lower())
        if q:
            term = f"%{q.lower()}%"
            query = query.where(
                (fn.LOWER(Service.title).contains(q.lower()))
                | (fn.LOWER(Service.description).contains(q.lower()))
            )
        rows = query.limit(limit).offset(offset)
        return [_service_to_dict(row) for row in rows]

    def create_service(
        self,
        owner_username: str,
        category_slug: str,
        title: str,
        description: str,
        price: float,
    ) -> dict:
        category = Category.get(Category.slug == category_slug)
        service = Service.create(
            owner_username=owner_username.lower(),
            category=category,
            title=title,
            description=description,
            price=price,
        )
        return _service_to_dict(service)

    def delete_service(self, service_id: int, owner_username: str) -> bool:
        try:
            service = Service.get(Service.id == service_id)
        except Service.DoesNotExist:
            return False
        if service.owner_username != owner_username.lower():
            return False
        service.delete_instance()
        return True

    # ----- users -----------------------------------------------------

    def list_users_with_aggregates(
        self,
        q: str | None = None,
        flt: str = "all",
        limit: int = 30,
        offset: int = 0,
    ) -> list[dict]:
        query = Users.select().order_by(Users.id.desc())
        if q:
            term = f"%{q.lower()}%"
            query = query.where(fn.LOWER(Users.username).contains(q.lower()))
        if flt == "arbiters":
            query = query.where(Users.admin >= 1)
        elif flt == "with_deposit":
            usernames = [d.user_username for d in Deposit.select(Deposit.user_username).where(Deposit.status == "active")]
            if usernames:
                query = query.where(Users.username.in_(usernames))
            else:
                return []
        rows = query.limit(limit).offset(offset)
        return [self.get_user_card_aggregate(u) for u in rows]

    def get_user_card_aggregate(self, user: Users | str) -> dict:
        if isinstance(user, str):
            user = Users.get_or_none(Users.username == user.lower())
            if user is None:
                return {}
        deposit_total = (
            Deposit.select(fn.COALESCE(fn.SUM(Deposit.amount), 0))
            .where((Deposit.user_username == user.username) & (Deposit.status == "active"))
            .scalar()
            or 0
        )
        rating_row = (
            Review.select(fn.AVG(Review.rating).alias("avg_rating"), fn.COUNT(Review.id).alias("cnt"))
            .where(Review.target_username == user.username)
            .dicts()
            .first()
        )
        rating = round(float(rating_row["avg_rating"] or 0.0), 1) if rating_row else 0.0
        reviews_count = rating_row["cnt"] if rating_row else 0
        deals_count = (
            Deals.select()
            .where(((Deals.buyer == user.username) | (Deals.seller == user.username)) & (Deals.status == SUCCESS))
            .count()
        )
        deals_sum = (
            Deals.select(fn.COALESCE(fn.SUM(Deals.sum), 0))
            .where(((Deals.buyer == user.username) | (Deals.seller == user.username)) & (Deals.status == SUCCESS))
            .scalar()
            or 0
        )
        prefix = None
        if user.admin >= 2:
            prefix = "admin"
        elif user.admin == 1:
            prefix = "arbiter"
        online = OnlineStatus.get_or_none(OnlineStatus.user_username == user.username)
        extra = ProfileExtra.get_or_none(ProfileExtra.user_username == user.username)
        return {
            "id": user.id,
            "user_id": user.user_id,
            "username": user.username,
            "balance": float(user.balance),
            "admin": int(user.admin),
            "prefix": prefix,
            "good": int(user.good),
            "bad": int(user.bad),
            "deposit": float(deposit_total),
            "rating": rating,
            "reviews_count": reviews_count,
            "deals_count": deals_count,
            "deals_sum": float(deals_sum),
            "online": bool(online and (datetime.now() - online.last_seen).total_seconds() < 300),
            "banner_url": extra.banner_url if extra else None,
            "description": extra.description if extra else "",
            "forums": json.loads(extra.forums) if extra and extra.forums else [],
        }

    def touch_online(self, username: str) -> None:
        username = username.lower()
        status, _ = OnlineStatus.get_or_create(user_username=username)
        status.last_seen = datetime.now()
        status.save()

    # ----- deposits --------------------------------------------------

    def list_deposits(self, username: str) -> list[dict]:
        rows = Deposit.select().where(Deposit.user_username == username.lower()).order_by(Deposit.created_at.desc())
        return [
            {
                "id": d.id,
                "amount": float(d.amount),
                "status": d.status,
                "created_at": d.created_at.isoformat(),
                "released_at": d.released_at.isoformat() if d.released_at else None,
            }
            for d in rows
        ]

    def create_deposit(self, username: str, amount: float) -> dict:
        deposit = Deposit.create(user_username=username.lower(), amount=amount)
        return {"id": deposit.id, "amount": float(amount), "status": "active"}

    def has_invoice_record(self, id_operation: int) -> bool:
        return Invoices.select().where(Invoices.id_operation == id_operation).exists()

    def release_deposit(self, deposit_id: int) -> bool:
        try:
            deposit = Deposit.get(Deposit.id == deposit_id)
        except Deposit.DoesNotExist:
            return False
        deposit.status = "released"
        deposit.released_at = datetime.now()
        deposit.save()
        return True

    # ----- reviews ---------------------------------------------------

    def list_reviews(self, target_username: str, limit: int = 30, offset: int = 0) -> list[dict]:
        rows = (
            Review.select()
            .where(Review.target_username == target_username.lower())
            .order_by(Review.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return [
            {
                "id": r.id,
                "deal_id": r.deal_id,
                "author_username": r.author_username,
                "target_username": r.target_username,
                "rating": int(r.rating),
                "text": r.text,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]

    def create_review(
        self,
        author_username: str,
        target_username: str,
        rating: int,
        text: str,
        deal_id: int | None = None,
    ) -> dict:
        rating = max(1, min(5, int(rating)))
        review = Review.create(
            author_username=author_username.lower(),
            target_username=target_username.lower(),
            rating=rating,
            text=text,
            deal_id=deal_id,
        )
        # bump good/bad on target user
        user = Users.get_or_none(Users.username == target_username.lower())
        if user is not None:
            if rating >= 4:
                user.good += 1
            elif rating <= 2:
                user.bad += 1
            user.save()
        return {
            "id": review.id,
            "deal_id": deal_id,
            "rating": rating,
            "text": text,
            "author_username": author_username.lower(),
            "target_username": target_username.lower(),
            "created_at": review.created_at.isoformat(),
        }

    # ----- notifications --------------------------------------------

    def list_notifications(
        self, username: str, type_: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        query = (
            Notification.select()
            .where(Notification.user_username == username.lower())
            .order_by(Notification.created_at.desc())
        )
        if type_:
            query = query.where(Notification.type == type_)
        return [
            {
                "id": n.id,
                "type": n.type,
                "title": n.title,
                "body": n.body,
                "payload": json.loads(n.payload or "{}"),
                "is_read": bool(n.is_read),
                "created_at": n.created_at.isoformat(),
            }
            for n in query.limit(limit).offset(offset)
        ]

    def count_notifications(self, username: str) -> dict:
        username = username.lower()
        result = {"all": 0, "deals": 0, "deposits": 0, "system": 0, "unread": 0}
        rows = (
            Notification.select(Notification.type, fn.COUNT(Notification.id).alias("c"))
            .where(Notification.user_username == username)
            .group_by(Notification.type)
            .dicts()
        )
        for row in rows:
            result["all"] += row["c"]
            if row["type"] in result:
                result[row["type"]] = row["c"]
        result["unread"] = (
            Notification.select()
            .where((Notification.user_username == username) & (Notification.is_read == False))  # noqa: E712
            .count()
        )
        return result

    def mark_notification_read(self, username: str, notification_id: int) -> bool:
        try:
            n = Notification.get(Notification.id == notification_id)
        except Notification.DoesNotExist:
            return False
        if n.user_username != username.lower():
            return False
        n.is_read = True
        n.save()
        return True

    def mark_all_notifications_read(self, username: str) -> int:
        return (
            Notification.update(is_read=True)
            .where((Notification.user_username == username.lower()) & (Notification.is_read == False))  # noqa: E712
            .execute()
        )

    def push_notification(
        self,
        username: str,
        type_: str,
        title: str,
        body: str = "",
        payload: dict | None = None,
    ) -> dict:
        n = Notification.create(
            user_username=username.lower(),
            type=type_,
            title=title,
            body=body,
            payload=json.dumps(payload or {}, ensure_ascii=False),
        )
        return {
            "id": n.id,
            "type": n.type,
            "title": n.title,
            "body": n.body,
            "payload": payload or {},
            "is_read": False,
            "created_at": n.created_at.isoformat(),
        }

    # ----- profile extras -------------------------------------------

    def get_profile_extra(self, username: str) -> dict:
        username = username.lower()
        extra = ProfileExtra.get_or_none(ProfileExtra.user_username == username)
        if extra is None:
            return {"description": "", "banner_url": None, "forums": [], "prefix": None}
        return {
            "description": extra.description or "",
            "banner_url": extra.banner_url,
            "forums": json.loads(extra.forums) if extra.forums else [],
            "prefix": extra.prefix,
        }

    def set_profile_description(self, username: str, description: str) -> None:
        username = username.lower()
        extra, _ = ProfileExtra.get_or_create(user_username=username)
        extra.description = description
        extra.save()

    def set_profile_banner(self, username: str, banner_url: str | None) -> None:
        username = username.lower()
        extra, _ = ProfileExtra.get_or_create(user_username=username)
        extra.banner_url = banner_url
        extra.save()

    def set_profile_forums(self, username: str, forums: Iterable[dict]) -> None:
        username = username.lower()
        extra, _ = ProfileExtra.get_or_create(user_username=username)
        extra.forums = json.dumps(list(forums), ensure_ascii=False)
        extra.save()

    # ----- support ---------------------------------------------------

    def list_support(self, kind: str) -> list[dict]:
        if kind == "admins":
            query = Users.select().where(Users.admin >= 2)
        elif kind == "arbiters":
            query = Users.select().where(Users.admin == 1)
        else:
            return []
        return [
            {
                "id": u.id,
                "user_id": u.user_id,
                "username": u.username,
                "admin": int(u.admin),
                "prefix": "admin" if u.admin >= 2 else "arbiter",
            }
            for u in query
        ]

    # ----- deals -----------------------------------------------------

    def list_user_deals(
        self,
        username: str,
        role: str = "all",
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        username = username.lower()
        query = Deals.select().order_by(Deals.id.desc())
        if role == "buyer":
            query = query.where(Deals.buyer == username)
        elif role == "seller":
            query = query.where(Deals.seller == username)
        else:
            query = query.where((Deals.buyer == username) | (Deals.seller == username))
        if status:
            query = query.where(Deals.status == status)
        return [
            {
                "id": d.id,
                "buyer": d.buyer,
                "seller": d.seller,
                "sum": float(d.sum),
                "description": d.description,
                "pay_comission": d.pay_comission,
                "status": d.status,
                "confirm_buyer": bool(d.confirm_buyer),
                "confirm_seller": bool(d.confirm_seller),
                "role": "buyer" if d.buyer == username else "seller",
                "created_at": d.created_at.isoformat() if d.created_at else None,
            }
            for d in query.limit(limit).offset(offset)
        ]


def _service_to_dict(service: Service) -> dict:
    return {
        "id": service.id,
        "owner_username": service.owner_username,
        "category": {
            "id": service.category.id,
            "slug": service.category.slug,
            "name": service.category.name,
            "icon_key": service.category.icon_key,
        },
        "title": service.title,
        "description": service.description,
        "price": float(service.price),
        "currency": service.currency,
        "status": service.status,
        "created_at": service.created_at.isoformat() if service.created_at else None,
    }
