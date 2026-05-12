from datetime import datetime

from peewee import (
    BigIntegerField,
    BooleanField,
    DateTimeField,
    FloatField,
    ForeignKeyField,
    IntegerField,
    Model,
    PostgresqlDatabase,  # noqa: F401  (kept for parity with the old code)
    PrimaryKeyField,
    SqliteDatabase,
    TextField,
)

from routers.utils import status_arbitrs


db = SqliteDatabase("database.db")


class BaseModel(Model):
    class Meta:
        database = db


# ---------------------------------------------------------------------------
# Legacy bot models (kept identical to the previous schema so existing
# databases keep working without migrations).
# ---------------------------------------------------------------------------


class Users(BaseModel):
    id = PrimaryKeyField()
    user_id = BigIntegerField(null=False, unique=True)
    username = TextField(null=False)
    balance = FloatField(null=False, default=0.0)
    admin = BigIntegerField(null=False, default=0)
    ban = BooleanField(null=False, default=False)
    good = BigIntegerField(null=False, default=0)
    bad = BigIntegerField(null=False, default=0)


class Deals(BaseModel):
    id = PrimaryKeyField()
    buyer = TextField(null=False)
    seller = TextField(null=False)
    sum = FloatField(null=False)
    description = TextField(null=False)
    pay_comission = TextField(null=False)
    status = TextField(null=False)
    confirm_buyer = BooleanField(null=False, default=False)
    confirm_seller = BooleanField(null=False, default=False)
    created_at = DateTimeField(default=datetime.now)


class Withdraws(BaseModel):
    id = PrimaryKeyField()
    user_id = BigIntegerField(null=False)
    amount = FloatField(null=False)
    id_operation = BigIntegerField(null=False)


class Invoices(BaseModel):
    id = PrimaryKeyField()
    user_id = BigIntegerField(null=False)
    amount = FloatField(null=False)
    id_operation = BigIntegerField(null=False)


class Arbitrs(BaseModel):
    id = PrimaryKeyField()
    deal_id = BigIntegerField(null=False)
    initiator = TextField(null=False)
    reason = TextField(null=False)
    status = TextField(null=False, default=status_arbitrs.WAIT_CONFIRMATION)
    arbitr = TextField(null=False, default="None")
    verdict = TextField(null=False, default="None")


class PercentInvoice(BaseModel):
    id = PrimaryKeyField()
    percent = BigIntegerField(null=False, default=8)


class PercentDeal(BaseModel):
    id = PrimaryKeyField()
    percent = BigIntegerField(null=False, default=5)


class WithdrawRequest(BaseModel):
    id = PrimaryKeyField()
    user_id = BigIntegerField(null=False)
    amount = FloatField(null=False)
    status = TextField(null=False, default="pending")
    created_at = DateTimeField(default=datetime.now)


class WithdrawSettings(BaseModel):
    id = PrimaryKeyField()
    mode = TextField(null=False, default="auto")


# ---------------------------------------------------------------------------
# New TMA models. These live alongside the legacy schema; creation is
# idempotent so deploying does not require a migration step.
# ---------------------------------------------------------------------------


class Category(BaseModel):
    id = PrimaryKeyField()
    slug = TextField(null=False, unique=True)
    name = TextField(null=False)
    icon_key = TextField(null=False, default="briefcase")
    sort_order = IntegerField(null=False, default=0)
    is_active = BooleanField(null=False, default=True)


class Service(BaseModel):
    id = PrimaryKeyField()
    owner_username = TextField(null=False, index=True)
    category = ForeignKeyField(Category, backref="services", on_delete="CASCADE")
    title = TextField(null=False)
    description = TextField(null=False, default="")
    price = FloatField(null=False, default=0.0)
    currency = TextField(null=False, default="USDT")
    status = TextField(null=False, default="active")  # active / hidden / blocked
    created_at = DateTimeField(default=datetime.now)


class Deposit(BaseModel):
    id = PrimaryKeyField()
    user_username = TextField(null=False, index=True)
    amount = FloatField(null=False)
    status = TextField(null=False, default="active")  # active / released / withdrawn
    created_at = DateTimeField(default=datetime.now)
    released_at = DateTimeField(null=True)


class Review(BaseModel):
    id = PrimaryKeyField()
    deal_id = BigIntegerField(null=True)
    author_username = TextField(null=False)
    target_username = TextField(null=False, index=True)
    rating = IntegerField(null=False, default=5)
    text = TextField(null=False, default="")
    created_at = DateTimeField(default=datetime.now)


class Notification(BaseModel):
    id = PrimaryKeyField()
    user_username = TextField(null=False, index=True)
    type = TextField(null=False, default="system")  # deals / deposits / system
    title = TextField(null=False)
    body = TextField(null=False, default="")
    payload = TextField(null=False, default="{}")
    is_read = BooleanField(null=False, default=False)
    created_at = DateTimeField(default=datetime.now)


class ProfileExtra(BaseModel):
    id = PrimaryKeyField()
    user_username = TextField(null=False, unique=True)
    banner_url = TextField(null=True)
    description = TextField(null=False, default="")
    forums = TextField(null=False, default="[]")  # JSON encoded array
    prefix = TextField(null=True)


class OnlineStatus(BaseModel):
    id = PrimaryKeyField()
    user_username = TextField(null=False, unique=True)
    last_seen = DateTimeField(default=datetime.now)


ALL_MODELS = [
    # legacy
    Users,
    Deals,
    Withdraws,
    Invoices,
    Arbitrs,
    PercentInvoice,
    PercentDeal,
    WithdrawRequest,
    WithdrawSettings,
    # new
    Category,
    Service,
    Deposit,
    Review,
    Notification,
    ProfileExtra,
    OnlineStatus,
]
