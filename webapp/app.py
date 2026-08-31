"""Shelf Plan -- meal plan, price check and shopping list, with accounts.

Run locally:   uv run uvicorn webapp.app:app --port 8000
Run in Docker: docker compose up
"""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import re
import sys

from fastapi import (
    Depends, FastAPI, HTTPException, Query, Request, Response, status,
)
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.supermarkets import (barcode as barcode_lib,  # noqa: E402
                              catalog, recipe_import, recipes,
                              resolve, stores, weekplan)

from . import (auth, autoprice, mailer, passwords, pricing, security,  # noqa: E402
               trickle)
from .db import (Plan, PlanVersion, PriceRecord, Product,  # noqa: E402
                 Recipe, User, get_session, init_db)

STATIC_DIR = Path(__file__).parent / "static"

# Stamped at image build time; falls back to the source mtime when running
# straight from a checkout.
APP_VERSION = os.getenv("APP_VERSION", "").strip() or "dev"
try:
    BUILD_STAMP = datetime.fromtimestamp(
        Path(__file__).stat().st_mtime, tz=timezone.utc).isoformat(timespec="seconds")
except Exception:  # noqa: BLE001
    BUILD_STAMP = ""

# Set to the public https origin once deployed, e.g. https://shelfplan.fly.dev
PUBLIC_URL = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
PUBLIC = bool(PUBLIC_URL)

app = FastAPI(title="Shelf Plan", version="1.0")


@app.middleware("http")
async def _harden(request: Request, call_next):
    """Attach security headers, and refuse plain http once public.

    The scheme comes from request.url after uvicorn has applied
    --proxy-headers, so behind Fly or Caddy this reflects what the browser
    actually used rather than the plaintext hop inside the network.
    """
    if PUBLIC and request.url.scheme == "http" and request.url.hostname not in (
            "localhost", "127.0.0.1"):
        return RedirectResponse(
            str(request.url.replace(scheme="https")), status_code=308)
    response = await call_next(request)
    for key, value in security.security_headers(https_only=PUBLIC).items():
        response.headers.setdefault(key, value)
    return response


@app.on_event("startup")
def _startup() -> None:
    init_db()
    if trickle.start():
        print(f"Catalogue top-up running: one request every "
              f"~{trickle.INTERVAL_S}s across {', '.join(trickle.STORES)}.",
              file=sys.stderr)
    if autoprice.start():
        where = autoprice.status()
        print(f"Weekly price check running: {where['day']}s at "
              f"{where['hour']:02d}:00, from the catalogue only.",
              file=sys.stderr)
    if auth.SECRET_WAS_GENERATED:
        print(
            "WARNING: SESSION_SECRET is unset, so a random one was generated. "
            "Everyone will be signed out on restart. Set SESSION_SECRET to fix.",
            file=sys.stderr,
        )
    problem = security.signup_config_error()
    if problem:
        print(f"WARNING: {problem}", file=sys.stderr)
    if PUBLIC and not auth.COOKIE_SECURE:
        print(
            "WARNING: PUBLIC_URL is set but COOKIE_SECURE is off, so session "
            "cookies would travel in clear. Set COOKIE_SECURE=1.",
            file=sys.stderr,
        )
    if PUBLIC and security.SIGNUP_MODE == "open":
        print(
            "NOTE: signup is open -- anyone with the URL can create an "
            "account. Set SIGNUP_MODE=invite to restrict it.",
            file=sys.stderr,
        )


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    invite: Optional[str] = Field(default=None, max_length=200)


class ForgotRequest(BaseModel):
    email: EmailStr


class ResetRequest(BaseModel):
    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class RecipeIn(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    data: Dict[str, Any] = Field(default_factory=dict)


class RecipePatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=300)
    rating: Optional[int] = Field(default=None, ge=1, le=5)
    notes: Optional[str] = Field(default=None, max_length=2000)
    clear_rating: bool = False
    # +1 for "cooked it", -1 to undo a mis-click. An absolute value can also be
    # set directly, which is what the counter's own control uses.
    cooked: int = Field(default=0, ge=-1, le=1)
    times_cooked: Optional[int] = Field(default=None, ge=0, le=9999)


class SaveRecipesRequest(BaseModel):
    recipes: List[Dict[str, Any]]


class DeleteRecipesRequest(BaseModel):
    """Which recipes to delete, named outright.

    Ids rather than "delete everything" on purpose. The page deletes what it is
    currently showing, and what it is showing depends on filters -- so the two
    have to agree on the exact list, or a filtered delete could take the lot.
    """
    ids: List[int] = Field(..., min_length=1, max_length=2000)


class ShopItemIn(BaseModel):
    """Add a product to the shopping list."""
    food: Optional[str] = Field(default=None, max_length=300)
    query: Optional[str] = Field(default=None, max_length=300)
    store: Optional[str] = Field(default=None, max_length=32)
    stockcode: Optional[str] = Field(default=None, max_length=40)
    aisle: str = Field(default="other", max_length=40)
    pack: Optional[float] = Field(default=None, gt=0, le=100_000)
    grams: Optional[float] = Field(default=None, gt=0, le=1_000_000)


class ImportRequest(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    servings: Optional[int] = Field(default=None, ge=1, le=50)
    system: str = Field(default="metric", max_length=10)


class RescaleRequest(BaseModel):
    recipe: Dict[str, Any]
    servings: Optional[int] = Field(default=None, ge=1, le=50)
    system: str = Field(default="metric", max_length=10)


class AutoPlanRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=14)
    meals_per_day: int = Field(default=3, ge=1, le=6)
    ceiling: float = Field(default=2000, ge=800, le=6000)
    floor_protein: float = Field(default=150, ge=20, le=400)
    floor_fibre: float = Field(default=25, ge=5, le=100)
    # Meal prep repeats on purpose, and repetition is most of what keeps a
    # trolley affordable: every extra distinct dish is another pack of
    # something. Three was a variety setting dressed up as a prep one.
    max_repeats: int = Field(default=5, ge=1, le=14)
    apply: bool = Field(default=False, description="Write it into the plan.")
    # Used only when the library is too thin and dishes have to be composed.
    cuisine: str = Field(default="any", max_length=40)
    diet: str = Field(default="any", max_length=20)
    # What the week's shopping should come to. Meal prep is repetitive on
    # purpose, and repetition is what keeps a trolley affordable.
    budget: Optional[float] = Field(default=None, ge=20, le=2000)


class RebalanceRequest(BaseModel):
    ingredients: List[Dict[str, Any]]
    food: str = Field(min_length=1, max_length=300)
    grams: float = Field(gt=0, le=20000)
    target: str = Field(default="p", max_length=4)


class ManualPrice(BaseModel):
    food: str = Field(min_length=1, max_length=300)
    price: float = Field(gt=0, le=10_000)
    pack: Optional[float] = Field(default=None, gt=0, le=100_000)
    store: str = Field(default="manual entry", max_length=120)


class PlanIn(BaseModel):
    name: str = Field(default="My plan", max_length=200)
    data: Dict[str, Any] = Field(default_factory=dict)


class PlanPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    data: Optional[Dict[str, Any]] = None


class RefreshRequest(BaseModel):
    store: str = Field(default="Woolworths (online)", max_length=120)
    apply_reviewed: bool = Field(
        default=False,
        description="Also apply matches the resolver flagged for review.",
    )
    stores: List[str] = Field(
        default_factory=lambda: list(stores.ALL_STORES),
        description="Which supermarkets to price against.",
    )


class GenerateRequest(BaseModel):
    seed: str = Field(default="week", max_length=120)
    meals: int = Field(default=5, ge=1, le=14)
    servings: int = Field(default=4, ge=1, le=20)
    kcal_per_serving: float = Field(default=600, ge=150, le=2000)
    protein_per_serving: float = Field(default=40, ge=5, le=200)
    diet: str = Field(default="any", max_length=20)
    cuisine: str = Field(default="any", max_length=32)
    exclude: List[str] = Field(default_factory=list)
    # Blank spreads them over the day: a breakfast, some lunches and dinners.
    meal: str = Field(default="", max_length=16)
    price: bool = Field(default=True, description="Cost it from live prices.")
    stores: List[str] = Field(default_factory=lambda: list(stores.ALL_STORES))


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------

@app.get("/api/auth/config")
def auth_config() -> Dict[str, Any]:
    """What the sign-in screen needs to know before anyone types anything."""
    return {
        "signupMode": security.SIGNUP_MODE,
        "inviteRequired": security.SIGNUP_MODE == "invite",
        "minPasswordLength": auth.MIN_PASSWORD_LENGTH,
    }


@app.post("/api/auth/register")
def register(
    body: Credentials,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    security.enforce(security.register_by_ip, security.client_ip(request),
                     "sign-up attempts from this address")
    security.check_signup_allowed(body.invite)
    user = auth.register_user(session, body.email, body.password)
    auth.set_session(response, user.id, user.session_version or 1)
    return {"id": user.id, "email": user.email}


@app.post("/api/auth/login")
def login(
    body: Credentials,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    ip = security.client_ip(request)
    account = body.email.strip().lower()
    # Both limits are checked before the password is verified, so a flood never
    # reaches the deliberately-expensive Argon2 hash.
    security.enforce(security.login_by_ip, ip,
                     "sign-in attempts from this address")
    security.enforce(security.login_by_account, account,
                     "sign-in attempts for this account")
    user = auth.authenticate(session, account, body.password)
    # A correct password clears the counters, so ordinary typos never
    # accumulate into a lockout for the real owner.
    security.login_by_ip.reset(ip)
    security.login_by_account.reset(account)
    auth.set_session(response, user.id, user.session_version or 1)
    return {"id": user.id, "email": user.email}


def _reset_link(request: Request, token: str) -> str:
    """Absolute URL for a reset token.

    PUBLIC_URL wins when set, because behind a proxy the request's own host
    may be the internal one. Falls back to what the request saw.
    """
    base = os.getenv("PUBLIC_URL", "").strip().rstrip("/")
    if not base:
        base = str(request.base_url).rstrip("/")
    return f"{base}/?reset={token}"


@app.post("/api/auth/forgot")
def forgot_password(
    body: ForgotRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Start a password reset.

    Always answers the same way. Confirming which addresses have accounts
    would turn this endpoint into a membership oracle.
    """
    ip = security.client_ip(request)
    security.enforce(security.forgot_by_ip, ip,
                     "password reset requests from this address")
    security.enforce(security.forgot_by_account, body.email.strip().lower(),
                     "password reset requests for this account")

    issued = passwords.issue(session, body.email, ip=ip)
    if issued is not None:
        user, token = issued
        subject, text = mailer.reset_email(
            _reset_link(request, token), passwords.TOKEN_TTL_MINUTES)
        mailer.send(user.email, subject, text)

    where = (f" Sent from {mailer.SMTP_FROM}; check the spam folder if it does "
             f"not appear." if mailer.configured()
             else " This server has no mail set up, so the link is in its log "
                  "-- ask whoever runs it.")
    return {
        "ok": True,
        "message": ("If that address has an account, a reset link is on its "
                    f"way. The link expires in {passwords.TOKEN_TTL_MINUTES} "
                    f"minutes.{where}"),
        "mailConfigured": mailer.configured(),
    }


@app.post("/api/auth/reset")
def reset_password(
    body: ResetRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Redeem a reset token and sign the user in on the new password."""
    security.enforce(security.reset_by_ip, security.client_ip(request),
                     "reset attempts from this address")
    auth.validate_password(body.password)
    try:
        user = passwords.redeem(session, body.token, body.password,
                                auth.hash_password)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    # Every previous session is now invalid, including any the attacker held.
    auth.set_session(response, user.id, user.session_version)
    return {"id": user.id, "email": user.email}


@app.post("/api/auth/change-password")
def change_password(
    body: ChangePasswordRequest,
    response: Response,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Change the password of a signed-in user, ending other sessions."""
    if not auth.verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED,
                            "That is not your current password.")
    auth.validate_password(body.new_password)
    passwords.change_password(session, user, body.new_password,
                              auth.hash_password)
    auth.set_session(response, user.id, user.session_version)
    return {"ok": True, "message": "Password changed. Other sessions signed out."}


@app.post("/api/auth/logout")
def logout(response: Response) -> Dict[str, bool]:
    auth.clear_session(response)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: Optional[User] = Depends(auth.optional_user)) -> Dict[str, Any]:
    if user is None:
        return {"signedIn": False}
    return {"signedIn": True, "id": user.id, "email": user.email}


# --------------------------------------------------------------------------
# Plans
# --------------------------------------------------------------------------

# How many versions of a plan to keep. Enough to walk back from a bad edit,
# not so many that the database grows without limit.
PLAN_HISTORY = 20


def _snapshot(session: Session, plan: Plan) -> None:
    """Keep the current contents before they are replaced."""
    current = plan.data or {}
    if not current:
        return
    session.add(PlanVersion(plan_id=plan.id, data=current))
    old = session.scalars(
        select(PlanVersion)
        .where(PlanVersion.plan_id == plan.id)
        .order_by(PlanVersion.id.desc())
        .offset(PLAN_HISTORY)
    ).all()
    for row in old:
        session.delete(row)


def _plan_summary(plan: Plan) -> Dict[str, Any]:
    return {
        "id": plan.id,
        "name": plan.name,
        "updatedAt": plan.updated_at.isoformat() if plan.updated_at else None,
    }


def _owned_plan(session: Session, user: User, plan_id: int) -> Plan:
    plan = session.get(Plan, plan_id)
    # Same 404 whether it is missing or someone else's, so plan ids cannot be
    # probed for existence.
    if plan is None or plan.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found.")
    return plan


@app.get("/api/plans")
def list_plans(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    plans = session.scalars(
        select(Plan).where(Plan.user_id == user.id).order_by(Plan.updated_at.desc())
    ).all()
    return {"plans": [_plan_summary(p) for p in plans]}


@app.post("/api/plans", status_code=status.HTTP_201_CREATED)
def create_plan(
    body: PlanIn,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    plan = Plan(user_id=user.id, name=body.name, data=body.data)
    session.add(plan)
    session.commit()
    return {**_plan_summary(plan), "data": plan.data}


@app.get("/api/plans/{plan_id}")
def read_plan(
    plan_id: int,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    plan = _owned_plan(session, user, plan_id)
    return {**_plan_summary(plan), "data": plan.data}


@app.put("/api/plans/{plan_id}")
def update_plan(
    plan_id: int,
    body: PlanPatch,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    plan = _owned_plan(session, user, plan_id)
    if body.name is not None:
        plan.name = body.name
    if body.data is not None:
        # Snapshot first: this endpoint replaces the whole document, so a
        # client-side mistake would otherwise be unrecoverable.
        _snapshot(session, plan)
        plan.data = body.data
    session.commit()
    return {**_plan_summary(plan), "data": plan.data}


@app.get("/api/plans/{plan_id}/history")
def plan_history(
    plan_id: int,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Earlier versions of this plan, newest first."""
    plan = _owned_plan(session, user, plan_id)
    rows = session.scalars(
        select(PlanVersion).where(PlanVersion.plan_id == plan.id)
        .order_by(PlanVersion.id.desc())).all()
    return {
        "versions": [
            {
                "id": r.id,
                "savedAt": r.saved_at.isoformat() if r.saved_at else None,
                "meals": sum(len(d.get("meals") or [])
                             for d in (r.data or {}).get("week") or []),
                "shopItems": len((r.data or {}).get("shop") or {}),
                "recipes": len((r.data or {}).get("recipes") or []),
            }
            for r in rows
        ]
    }


@app.post("/api/plans/{plan_id}/undo")
def undo_plan(
    plan_id: int,
    version: Optional[int] = Query(None, description="A specific version id."),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Put a plan back to how it was before the last change.

    The version being replaced is itself snapshotted, so undo can be undone.
    """
    plan = _owned_plan(session, user, plan_id)
    stmt = select(PlanVersion).where(PlanVersion.plan_id == plan.id)
    if version is not None:
        stmt = stmt.where(PlanVersion.id == version)
    row = session.scalars(stmt.order_by(PlanVersion.id.desc())).first()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            "There is no earlier version of this plan.")

    restored_at = row.saved_at.isoformat() if row.saved_at else ""
    _snapshot(session, plan)
    plan.data = row.data
    session.delete(row)
    session.commit()
    return {**_plan_summary(plan), "restoredFrom": restored_at,
            "data": plan.data}


@app.delete("/api/plans/{plan_id}")
def delete_plan(
    plan_id: int,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, bool]:
    plan = _owned_plan(session, user, plan_id)
    session.delete(plan)
    session.commit()
    return {"ok": True}


# --------------------------------------------------------------------------
# Prices
# --------------------------------------------------------------------------

@app.get("/api/search")
def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
    store: Optional[str] = Query(None, description="Comma-separated store names."),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Search both supermarkets, with pack size and per-kg price intact."""
    wanted = [s.strip() for s in store.split(",")] if store else None
    return pricing.search_all(session, q, limit=limit, store_names=wanted)


@app.get("/api/compare")
def compare(
    food: str = Query(..., min_length=1, max_length=300),
    query: Optional[str] = Query(None, max_length=300),
    pack: Optional[float] = Query(None, gt=0, le=100_000),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Price one food at both supermarkets and say which is cheaper."""
    return pricing.compare_food(session, food, query or food, target_pack_g=pack)


@app.post("/api/recipes/generate")
def generate_recipes(
    body: GenerateRequest,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Compose recipes to the requested targets and cost the shopping list.

    Each line is priced at every requested store, so the list shows where each
    ingredient is cheapest rather than assuming one supermarket.
    """
    security.enforce(security.refresh_by_user, str(user.id),
                     "recipe builds")
    built = recipes.build_plan(
        seed=body.seed, meals=body.meals, servings=body.servings,
        kcal_per_serving=body.kcal_per_serving,
        protein_per_serving=body.protein_per_serving,
        diet=body.diet, exclude=body.exclude, cuisine=body.cuisine,
        # One meal named builds only that; blank spreads them across the day
        # rather than handing back five dinners.
        meals_wanted=([body.meal] if body.meal
                      else list(recipes.MEALS)),
    )
    shop = recipes.shopping_list(built)

    if not body.price:
        return {"recipes": built, "shop": shop, "priced": False}

    priced: Dict[str, Any] = {}
    basket: Dict[str, float] = {s: 0.0 for s in body.stores}
    best_total = 0.0
    for food, line in shop.items():
        comparison = pricing.compare_food(
            session, food, line["woo"], target_pack_g=line.get("pack"),
            store_names=body.stores)
        packs = line.get("packsNeeded") or 1
        per_store = {}
        for name, r in comparison["byStore"].items():
            cost = round(r["price"] * packs, 2) if r.get("price") else None
            per_store[name] = {
                "perKg": r.get("per_kg"), "packPrice": r.get("price"),
                "lineCost": cost, "matched": r.get("matched_name"),
                "needsReview": r.get("needs_review"),
                "onSpecial": r.get("on_special"),
            }
            if cost is not None and name in basket:
                basket[name] += cost
        cheapest = comparison.get("cheapest")
        if cheapest and per_store.get(cheapest, {}).get("lineCost"):
            best_total += per_store[cheapest]["lineCost"]
        priced[food] = {
            **line, "byStore": per_store, "cheapest": cheapest,
            "saving": comparison.get("saving"), "packsNeeded": packs,
        }

    return {
        "recipes": built,
        "shop": priced,
        "priced": True,
        "totals": {
            "byStore": {k: round(v, 2) for k, v in basket.items()},
            "cheapestMixed": round(best_total, 2),
        },
    }


@app.get("/api/recipes/browse")
def browse_recipes(
    cuisine: str = "any",
    diet: str = "any",
    category: str = "",
    meal: str = "",
    kcal: float = 600,
    protein: float = 40,
    servings: int = 4,
    limit: int = 48,
    offset: int = 0,
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """A page of every dish a theme can make.

    The builder answers "what should I eat to hit these numbers". This answers
    the other question people actually ask, which is "show me what there is".
    """
    return recipes.browse(
        cuisine=cuisine, diet=diet, category=category or None,
        meal=meal or None,
        servings=max(1, min(int(servings), 12)),
        kcal_per_serving=kcal, protein_per_serving=protein,
        limit=max(1, min(int(limit), 120)), offset=max(0, int(offset)))


def ingredient_prices(session: Session) -> Dict[str, Dict[str, Any]]:
    """What each ingredient costs a pack, from the catalogue only.

    Read entirely from what has already been fetched, because this runs while
    somebody is waiting for a week to be planned -- ninety live lookups would
    take four minutes and get the address blocked. An ingredient the catalogue
    has never seen has no price, and the planner treats it as free rather than
    refusing to plan.

    The match comes from the resolver rather than the plainest name in the
    catalogue. Taking the shortest name priced chicken breast off an 80g packet
    of sliced deli meat and then divided it into a one-kilo pack, which is the
    kind of arithmetic that makes a budget meaningless. Price and pack size are
    always taken from the same product, for the same reason.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for food, meta in recipes.INGREDIENTS.items():
        candidates = pricing.catalogue_search(
            session, query=meta["query"], store="woolworths", limit=12)
        products = candidates.get("products") or []
        if not products:
            # The full query carries words no label has -- "420g tin", "12
            # pack" -- so fall back the same way the pictures do.
            plain = food.split(",")[0]
            for attempt in (plain, " ".join(plain.split()[:2])):
                products = (pricing.catalogue_search(
                    session, query=attempt, store="woolworths",
                    limit=12).get("products") or [])
                if products:
                    break
        if not products:
            continue
        result = resolve.resolve_from_products(
            food, meta["query"], products, target_pack_g=meta.get("pack"))
        if result.get("status") != "ok" or not result.get("price"):
            continue

        # For a budget, the cheapest kilo among the products that are plainly
        # the same thing beats the one whose pack happens to match the plan.
        # Someone shopping to a number buys the kilo of chicken breast, not the
        # 450g organic pack that sits closer to the recipe's portion.
        wanted = f'{meta["query"]} {food}'
        winner = {"name": result.get("matched_name"),
                  "pack_g": result.get("gross_pack_g") or result.get("pack"),
                  "per_kg": result.get("per_kg"),
                  "pack_price": result.get("price")}
        top = resolve.name_similarity(wanted, winner["name"] or "")

        def as_good(alt: Dict[str, Any]) -> bool:
            """Only a product that is equally the right thing may undercut it.

            Cheapest-of-the-alternatives on its own priced chicken breast off a
            prosciutto-wrapped ready meal: the alternatives are the second to
            fourth best matches, and second best can be something else
            entirely.
            """
            name = alt.get("name") or ""
            return (resolve.name_similarity(wanted, name) >= top
                    and not resolve.conflict_penalty(wanted, name)
                    and not resolve.form_penalty(wanted, name)
                    and not resolve.processed_penalty(wanted, name))

        choices = [winner] + [
            a for a in (result.get("alternatives") or [])
            if a.get("pack_price") and a.get("per_kg") and as_good(a)]
        priced = [c for c in choices if c.get("pack_price") and c.get("per_kg")]
        best = min(priced, key=lambda c: c["per_kg"]) if priced else winner
        out[food] = {
            "price": best.get("pack_price") or result["price"],
            "pack": best.get("pack_g") or meta.get("pack"),
            "product": best.get("name") or result.get("matched_name", ""),
            "perKg": best.get("per_kg") or result.get("per_kg"),
        }
    return out


@app.get("/api/ingredient-prices")
def ingredient_price_table(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """The table above, for anything that wants to show its working."""
    table = ingredient_prices(session)
    return {"prices": table, "count": len(table),
            "of": len(recipes.INGREDIENTS)}


@app.get("/api/nutrition/estimate")
def estimate_nutrition(
    name: str = Query(..., min_length=1, max_length=200),
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Per-100g figures for a product name, from the ingredient table.

    Written-your-own recipes read their nutrition from Open Food Facts, which
    only answers to a barcode and often does not have Australian store lines at
    all. When it cannot, every figure came back zero and the recipe went into
    the week reading 0 kcal -- with nothing on screen saying why.

    A store name still describes a food, so match it against the ingredients
    already carrying figures. "Woolworths RSPCA Chicken Breast Fillet 1kg" is
    chicken breast whether or not anyone has scanned it.
    """
    best_name = None
    best_score = 0.0
    for food, meta in recipes.INGREDIENTS.items():
        for candidate in (food, meta["query"]):
            score = resolve.name_similarity(candidate, name)
            if score > best_score:
                best_name, best_score = food, score

    # A loose threshold is worse than no answer. At 0.34 a Cadbury Dairy Milk
    # block matched "Milk, skim" and would have been presented as 35 kcal per
    # 100g, which is not a near miss but a wrong number stated confidently.
    if not best_name or best_score < 0.55:
        return {"status": "not_found", "name": name,
                "message": "No ingredient close enough to estimate from."}

    meta = recipes.INGREDIENTS[best_name]
    return {
        "status": "ok",
        "name": name,
        "matched": best_name,
        "confidence": round(best_score, 2),
        "per100": {k: meta[k] for k in ("kcal", "p", "c", "f", "fb")},
    }


@app.get("/api/food-images")
def food_images(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """A photograph for every ingredient the builder can use.

    A generated recipe has no photograph of its own and inventing one would be
    a lie about a dish nobody has cooked. What is honest, and turns out to be
    more useful, is showing what actually goes in it: these are the real
    product shots from the catalogue, already fetched for pricing.
    """
    wanted = {name: meta["query"] for name, meta in recipes.INGREDIENTS.items()}
    found: Dict[str, str] = {}
    for name, query in wanted.items():
        # The catalogue requires every word to appear, which is right for a
        # search box and wrong here: the shopping queries carry words no label
        # has -- "420g tin", "12 pack", "RSPCA" -- so the strictest form finds
        # nothing for exactly the staples most worth a picture. Loosen a step
        # at a time and stop at the first thing that answers.
        plain = name.split(",")[0]
        # The pack size in a shopping query is the part no product label
        # repeats, so dropping it is the first and usually the only step
        # needed: "Burghul Wheat 500g" finds nothing, "Burghul Wheat" finds it.
        unsized = " ".join(w for w in query.split()
                           if not re.match(r"^\d+(?:\.\d+)?(?:g|kg|ml|l|pk)?$", w, re.I)
                           and w.lower() not in ("pack", "tin", "tins", "jar"))
        attempts = [query, unsized, plain,
                    " ".join(plain.split()[:2]), plain.split()[0]]
        for attempt in attempts:
            if not attempt:
                continue
            hit = pricing.catalogue_search(
                session, query=attempt, store="woolworths", limit=4)
            image = next((p["image"] for p in hit.get("products", [])
                          if p.get("image")), None)
            if image:
                found[name] = image
                break
    return {"images": found, "count": len(found), "of": len(wanted)}


@app.post("/api/recipes/import")
def import_recipe(
    body: ImportRequest,
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Read a recipe from a page the user links to.

    An importer, not a search engine: the method text belongs to whoever wrote
    it, so this fetches one page on request, keeps it for that account, and
    credits the source rather than building a searchable store of other
    people's writing.
    """
    security.enforce(security.import_by_user, str(user.id), "recipe imports")
    result = recipe_import.fetch(body.url)
    if result.get("status") != "success":
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            result.get("message", "Could not read that page."))
    scaled = recipe_import.scale_recipe(
        result["recipe"], body.servings, body.system)
    return {"recipe": scaled}


@app.post("/api/recipes/rescale")
def rescale_recipe(
    body: RescaleRequest,
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Re-present an already-imported recipe at a new size or unit system."""
    return {"recipe": recipe_import.scale_recipe(
        body.recipe, body.servings, body.system)}


@app.post("/api/recipes/options")
def recipe_options(
    body: GenerateRequest,
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Several different recipes for one slot, labelled A, B, C.

    Used by the builder so a meal can be chosen rather than accepted.
    """
    options = recipes.build_options(
        seed=body.seed, count=min(body.meals, 5), servings=body.servings,
        kcal_per_serving=body.kcal_per_serving,
        protein_per_serving=body.protein_per_serving,
        diet=body.diet, exclude=body.exclude, cuisine=body.cuisine,
    )
    return {"options": options}


@app.get("/api/barcode/{code}")
def scan_barcode(
    code: str,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """What a scanned barcode is.

    Checks what this server already knows before asking anyone, so a repeat
    scan of the same tin costs nothing and works offline from the stores.
    """
    clean = barcode_lib.normalise(code)
    if not barcode_lib.valid(clean):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "That is not a readable barcode.")

    known = pricing.by_barcode(session, clean)
    if known:
        return {"status": "success", "barcode": clean, "product": known,
                "nutrition": None, "sources": ["catalogue"], "cached": True}

    security.enforce(security.import_by_user, str(user.id), "barcode lookups")
    result = barcode_lib.look_up(clean)
    if result.get("status") == "success" and result.get("product"):
        # Remember it, so the next scan of this product is instant.
        try:
            pricing.remember_products(session, "woolworths", [result["product"]])
        except Exception:  # noqa: BLE001
            session.rollback()
    return result


@app.post("/api/plans/{plan_id}/autoplan")
def autoplan(
    plan_id: int,
    body: AutoPlanRequest,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Fill the week so each day meets its targets, cooking to fill gaps.

    Planning from the saved library alone means a new account is told to go and
    build recipes first, which is the wrong answer to "plan my week for me".
    Where the library is too thin to fill seven days without repeating itself,
    the missing dishes are composed to the same targets and saved -- so what
    was planned is a real recipe you can rate, cook, or delete.
    """
    plan = _owned_plan(session, user, plan_id)
    rows = list(session.scalars(
        select(Recipe).where(Recipe.user_id == user.id)).all())

    # Counting recipes was the wrong question. A library of a dozen dinners is
    # twelve recipes and no breakfasts, so the count said "enough" and the
    # planner produced seven days of lunch and dinner with the morning empty.
    # What has to be enough is each sitting separately.
    prices = ingredient_prices(session)
    # A budget is really a limit on what protein may cost, because protein is
    # what the week is built around and what most of the money goes on. Three
    # quarters of the straight division leaves room for pack rounding: a
    # recipe's ingredients cost less than the packs you have to buy to get
    # them.
    protein_rate = None
    if body.budget:
        protein_rate = (body.budget / max(1.0, body.days * body.floor_protein)
                        * 0.75)

    sittings = weekplan.sittings_for(body.meals_per_day)
    # How many dishes a sitting needs is not simply the number of days. Most
    # savoury dishes suit lunch *and* dinner, so one pool has to cover both:
    # four dishes repeating three times each is twelve servings against the
    # fourteen a week of lunches and dinners wants, and the seventh day ran out
    # with nothing left to put on it. Breakfast has its own pool and its own
    # smaller need.
    shared = max(1, len([s for s in sittings if s != "breakfast"]))
    repeats = max(1, body.max_repeats)

    for sitting in sittings:
        covers = 1 if sitting == "breakfast" else shared
        need_each = max(3, -(-body.days * covers // repeats) + 1)
        have = sum(1 for r in rows
                   if weekplan.recipe_suits(_recipe_json(r), sitting))
        if have >= need_each:
            continue
        existing = {r.name for r in rows}
        fresh = recipes.build_plan(
            seed=f"auto:{user.id}:{plan_id}:{sitting}:{len(rows)}",
            meals=need_each - have, servings=4,
            # Aim under the ceiling and over the floor. Dividing them evenly
            # leaves the packer no room at all: three meals at exactly a third
            # of the ceiling fail the day on the first rounding.
            kcal_per_serving=max(
                200.0, body.ceiling / max(1, body.meals_per_day) * 0.9),
            protein_per_serving=max(
                10.0, body.floor_protein / max(1, body.meals_per_day) * 1.15),
            diet=body.diet or "any", cuisine=body.cuisine or "any",
            meals_wanted=[sitting],
            prices=prices, cost_ceiling=protein_rate,
            # Without the fibre floor the builder optimises for calories and
            # protein alone, and every composed day then lands on target for
            # both and short on fibre -- which is exactly the miss the planner
            # was asked to avoid.
            targets={"kcal": max(200.0, body.ceiling
                                 / max(1, body.meals_per_day) * 0.9),
                     "protein": max(10.0, body.floor_protein
                                    / max(1, body.meals_per_day) * 1.15),
                     "fibreMin": max(2.0, body.floor_fibre
                                     / max(1, body.meals_per_day) * 1.15)})
        for item in (fresh or []):
            name = str(item.get("name") or "").strip()[:300]
            if not name or name in existing:
                continue
            payload = {k: v for k, v in item.items() if k != "name"}
            row = Recipe(user_id=user.id, name=name, data=payload)
            session.add(row)
            rows.append(row)
            existing.add(name)
    session.commit()

    library = [_recipe_json(r) for r in rows]

    goals = {"ceiling": body.ceiling, "floorP": body.floor_protein,
             "floorF": body.floor_fibre}
    def run(lib: List[Dict[str, Any]]) -> Dict[str, Any]:
        return weekplan.plan_week(
            lib, goals, days=body.days, meals_per_day=body.meals_per_day,
            max_repeats=body.max_repeats, prices=prices, budget=body.budget)

    result = run(library)

    # A budget is useless if the library is already stocked with expensive
    # dishes: the top-up above only fires when a sitting is short, so a library
    # built without a budget stays expensive forever and the number the user
    # typed does nothing. If the week comes in over, cook a cheap round and try
    # again -- once, and only keep it if it is genuinely better.
    over = (body.budget and result.get("eatenCost")
            and result["eatenCost"] > body.budget)
    if over and prices:
        existing = {r.name for r in rows}
        cheaper: List[Dict[str, Any]] = []
        for sitting in sittings:
            cheaper += recipes.build_plan(
                seed=f"thrift:{user.id}:{plan_id}:{sitting}:{len(rows)}",
                meals=4, servings=4,
                kcal_per_serving=max(
                    200.0, body.ceiling / max(1, body.meals_per_day) * 0.9),
                protein_per_serving=max(
                    10.0, body.floor_protein / max(1, body.meals_per_day) * 1.15),
                diet=body.diet or "any", cuisine=body.cuisine or "any",
                meals_wanted=[sitting], prices=prices,
                cost_ceiling=protein_rate or 0.1,
                targets={"kcal": max(200.0, body.ceiling
                                     / max(1, body.meals_per_day) * 0.9),
                         "protein": max(10.0, body.floor_protein
                                        / max(1, body.meals_per_day) * 1.15),
                         "fibreMin": max(2.0, body.floor_fibre
                                         / max(1, body.meals_per_day) * 1.15)})
        # Try the plan before committing anything. A rejected attempt used to
        # leave its dishes in the library anyway, so the *next* plan picked
        # them up and came out worse -- a failed experiment quietly poisoning
        # the thing it was testing.
        fresh = [item for item in cheaper
                 if str(item.get("name") or "").strip()
                 and item["name"] not in existing]
        if fresh:
            trial = library + [
                {**item, "id": f"trial-{n}"} for n, item in enumerate(fresh)]
            second = run(trial)
            # Better means cheaper without giving up days on target.
            if (second.get("eatenCost") is not None
                    and second["eatenCost"] < result["eatenCost"]
                    and second["daysMeetingTargets"]
                    >= result["daysMeetingTargets"]):
                kept = {}
                for item in fresh:
                    row = Recipe(user_id=user.id, name=item["name"][:300],
                                 data={k: v for k, v in item.items()
                                       if k != "name"})
                    session.add(row)
                    rows.append(row)
                    kept[f"trial-{len(kept)}"] = row
                session.commit()
                # The trial referred to dishes by placeholder id; the plan has
                # to point at the rows that were actually saved.
                real = {f"trial-{n}": row.id
                        for n, row in enumerate(list(kept.values()))}
                for day in second["days"]:
                    for meal in day["meals"]:
                        if meal["recipeId"] in real:
                            meal["recipeId"] = real[meal["recipeId"]]
                result = second
                result["cheaperRoundAdded"] = len(fresh)
                library = [_recipe_json(r) for r in rows]

    if body.apply and result["days"]:
        names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
                 "Saturday", "Sunday"]
        data = dict(plan.data or {})
        _snapshot(session, plan)
        data["week"] = [
            {"day": names[i % 7], "meals": day["meals"]}
            for i, day in enumerate(result["days"][:7])
        ]
        meta = dict(data.get("meta") or {})
        meta.update({"ceiling": body.ceiling, "floorP": body.floor_protein,
                     "floorF": body.floor_fibre})
        data["meta"] = meta
        plan.data = data
        session.commit()
        result["applied"] = True

    result["library"] = library
    return result


@app.post("/api/rebalance")
def rebalance(
    body: RebalanceRequest,
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Change one ingredient, and say what restores the target."""
    return weekplan.rebalance(body.ingredients, body.food, body.grams, body.target)


@app.get("/api/swaps")
def swaps(
    food: str = Query(..., min_length=1, max_length=300),
    priced: bool = Query(True),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """What else could go in, and what it would change.

    Prices come from the local catalogue only, so this is instant and does not
    put a request to the supermarkets behind a hover.
    """
    options = recipes.swaps_for(food)
    if priced:
        for option in options:
            hits = pricing.catalogue_search(
                session, query=option["query"], limit=3, sort="cheapest")
            best = next((p for p in hits["products"] if p.get("per_kg")), None)
            option["perKg"] = best["per_kg"] if best else None
            option["matched"] = best["name"] if best else None
            option["image"] = best.get("image") if best else ""
    return {"food": food, "options": options}


@app.get("/api/foods")
def foods(user: User = Depends(auth.current_user)) -> Dict[str, Any]:
    """Per-100g figures for everything the builder knows about."""
    return {"foods": recipes.food_table()}


@app.get("/api/price")
def price(
    food: str = Query(..., min_length=1, max_length=300),
    query: Optional[str] = Query(None, max_length=300),
    pack: Optional[float] = Query(None, gt=0, le=100_000),
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Price one planned food on the plan's own basis."""
    return resolve.resolve_food(food, query or food, target_pack_g=pack)


def _record_price(
    session: Session, user_id: int, result: Dict[str, Any], store: str
) -> None:
    """Store one reading, replacing today's earlier reading for that food."""
    today = date.today().isoformat()
    existing = session.scalar(
        select(PriceRecord).where(
            PriceRecord.user_id == user_id,
            PriceRecord.food == result["food"],
            PriceRecord.observed_on == today,
            PriceRecord.source == "woolworths-api",
        )
    )
    target = existing or PriceRecord(
        user_id=user_id,
        food=result["food"],
        observed_on=today,
        source="woolworths-api",
    )
    target.price = result["price"]
    target.pack = result.get("pack")
    target.per_kg = result.get("per_kg")
    target.basis = result.get("basis", "gross")
    target.store = store
    target.matched_name = result.get("matched_name") or ""
    target.stockcode = str(result.get("stockcode") or "")
    target.on_special = bool(result.get("on_special"))
    target.was_price = result.get("was_price")
    if existing is None:
        session.add(target)


@app.post("/api/plans/{plan_id}/refresh-prices")
def refresh_prices(
    plan_id: int,
    body: RefreshRequest,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Re-price the plan's shopping list from live data.

    Appends to each food's history rather than rewriting it, and holds back
    low-confidence matches unless explicitly asked to apply them.
    """
    security.enforce(security.refresh_by_user, str(user.id),
                     "price refreshes")
    plan = _owned_plan(session, user, plan_id)
    data = dict(plan.data or {})
    # Copied one level deeper than looks necessary, on purpose. `plan.data` is
    # a plain JSON column, so SQLAlchemy detects changes by comparing against
    # the value it loaded -- and a nested dict mutated in place IS that value,
    # so the comparison sees nothing new and skips the UPDATE entirely. When
    # every price happened to match today's existing record, that silently
    # discarded the picture this loop attaches.
    shop = {k: dict(v or {}) for k, v in (data.get("shop") or {}).items()}
    prices = dict(data.get("prices") or {})
    today = date.today().isoformat()

    applied: List[Dict[str, Any]] = []
    review: List[Dict[str, Any]] = []

    for food, meta in shop.items():
        history = list(prices.get(food) or [])
        previous = history[-1] if history else None
        target_pack = (previous or {}).get("pack") or (meta or {}).get("pack")

        # A product chosen by hand stays chosen. Re-resolving would hand the
        # line straight back to the match that was rejected, so swapping would
        # appear to work and then quietly undo itself on the next refresh.
        pinned = pricing.pinned_product(session, meta or {})
        if pinned:
            record = {
                "price": pinned["pack_price"],
                "pack": pinned.get("pack_g") or target_pack,
                "date": today,
                "store": pinned.get("store") or "woolworths",
                "source": "chosen by hand",
                "matched": pinned.get("name", ""),
            }
            if pinned.get("url"):
                record["url"] = pinned["url"]
            if pinned.get("on_special"):
                record["onSpecial"] = True
            if pinned.get("was_price"):
                record["wasPrice"] = pinned["was_price"]
            if history and history[-1].get("date") == today:
                history[-1] = record
            else:
                history.append(record)
            prices[food] = history
            if pinned.get("image") and not shop.get(food, {}).get("image"):
                shop.setdefault(food, {})["image"] = pinned["image"]
            applied.append({"food": food, "price": record["price"],
                            "matched": record["matched"], "pinned": True})
            continue

        comparison = pricing.compare_food(
            session, food, (meta or {}).get("woo") or food,
            target_pack_g=target_pack, store_names=body.stores)
        # Prefer the cheapest confident match; fall back to whichever store
        # answered at all so a single-store outage does not stall the refresh.
        result = None
        if comparison.get("cheapest"):
            result = comparison["byStore"][comparison["cheapest"]]
        else:
            for candidate in comparison.get("byStore", {}).values():
                if candidate.get("status") == "ok" and candidate.get("price"):
                    result = candidate
                    break
        if result is None:
            review.append({"food": food, "status": "not_found",
                           "review_reasons": ["no store returned a usable price"],
                           "previous": previous})
            continue
        result["previous"] = previous

        usable = (
            result["status"] == "ok"
            and result.get("price") is not None
            and result.get("pack")
        )
        if not usable:
            review.append(result)
            continue
        if result.get("needs_review") and not body.apply_reviewed:
            review.append(result)
            continue

        record = {
            "price": result["price"],
            "pack": result["pack"],
            "date": today,
            "store": body.store,
            "source": "woolworths-api",
            "matched": result["matched_name"],
        }
        if result.get("stockcode"):
            record["stockcode"] = result["stockcode"]
        if result.get("url"):
            record["url"] = result["url"]
        if result.get("on_special"):
            record["onSpecial"] = True
        # The shelf's own before-price. With one reading there is no history to
        # compare against, and this is the store telling you outright.
        if result.get("was_price"):
            record["wasPrice"] = result["was_price"]

        if history and history[-1].get("date") == today:
            history[-1] = record  # one reading per day
        else:
            history.append(record)
        prices[food] = history
        # Lines added by hand or imported have no picture; a refresh is the
        # natural moment to attach one from whatever product matched.
        if result.get("image") and not shop.get(food, {}).get("image"):
            shop.setdefault(food, {})["image"] = result["image"]
        if result.get("url") and not shop.get(food, {}).get("url"):
            shop.setdefault(food, {})["url"] = result["url"]
        _record_price(session, user.id, result, body.store)
        applied.append(result)

    data["prices"] = prices
    data["shop"] = shop
    plan.data = data
    session.commit()

    return {
        "applied": len(applied),
        "heldBack": len(review),
        "changes": [
            {
                "food": r["food"],
                "matched": r.get("matched_name"),
                "perKg": r.get("per_kg"),
                "previousPerKg": (
                    r["previous"]["price"] / (r["previous"]["pack"] / 1000)
                    if r.get("previous") and r["previous"].get("pack")
                    else None
                ),
                "onSpecial": r.get("on_special"),
            }
            for r in applied
        ],
        "review": [
            {
                "food": r["food"],
                "matched": r.get("matched_name"),
                "perKg": r.get("per_kg"),
                "reasons": r.get("review_reasons") or [r.get("message", "no match")],
                "confidence": r.get("confidence"),
            }
            for r in review
        ],
    }


@app.get("/api/price-history")
def price_history(
    food: Optional[str] = Query(None, max_length=300),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Observed prices over time, for one food or all of them."""
    stmt = select(PriceRecord).where(PriceRecord.user_id == user.id)
    if food:
        stmt = stmt.where(PriceRecord.food == food)
    rows = session.scalars(stmt.order_by(PriceRecord.observed_on)).all()
    return {
        "records": [
            {
                "food": r.food,
                "price": r.price,
                "pack": r.pack,
                "perKg": r.per_kg,
                "basis": r.basis,
                "store": r.store,
                "matched": r.matched_name,
                "onSpecial": r.on_special,
                "date": r.observed_on,
            }
            for r in rows
        ]
    }


# --------------------------------------------------------------------------
# Recipe library
# --------------------------------------------------------------------------

def _recipe_json(recipe: Recipe) -> Dict[str, Any]:
    # The stored payload is spread FIRST so the database columns win. A recipe
    # from the builder carries its own "id" ("ragu-1") and "notes", and letting
    # those overwrite the real row id makes every later PATCH or DELETE address
    # a recipe that does not exist.
    data = dict(recipe.data or {})
    # Recipes saved before categories existed have none stored. Derive it from
    # the ingredients on the way out, so an existing library groups properly
    # instead of collapsing into "Other".
    if not data.get("category"):
        data["category"] = recipes.category_for(data)
    return {
        **data,
        "id": recipe.id,
        "name": recipe.name,
        "rating": recipe.rating,
        "notes": recipe.notes,
        "timesCooked": recipe.times_cooked,
        "updatedAt": recipe.updated_at.isoformat() if recipe.updated_at else None,
    }


def _owned_recipe(session: Session, user: User, recipe_id: int) -> Recipe:
    recipe = session.get(Recipe, recipe_id)
    if recipe is None or recipe.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Recipe not found.")
    return recipe


@app.get("/api/recipes")
def list_recipes(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """The saved library, best-rated first, then most recent."""
    rows = session.scalars(
        select(Recipe).where(Recipe.user_id == user.id)
    ).all()
    rows.sort(key=lambda r: (-(r.rating or 0), -(r.id or 0)))
    return {"recipes": [_recipe_json(r) for r in rows]}


@app.post("/api/recipes", status_code=status.HTTP_201_CREATED)
def create_recipe(
    body: RecipeIn,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    recipe = Recipe(user_id=user.id, name=body.name, data=body.data)
    session.add(recipe)
    session.commit()
    return _recipe_json(recipe)


@app.post("/api/recipes/save-many", status_code=status.HTTP_201_CREATED)
def save_recipes(
    body: SaveRecipesRequest,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Store a batch from the builder, skipping ones already saved by name."""
    existing = {
        r.name for r in session.scalars(
            select(Recipe).where(Recipe.user_id == user.id)).all()
    }
    saved = []
    for item in body.recipes:
        name = str(item.get("name") or "").strip()[:300]
        if not name or name in existing:
            continue
        payload = {k: v for k, v in item.items()
                   if k not in ("name", "id", "rating", "notes", "timesCooked")}
        recipe = Recipe(user_id=user.id, name=name, data=payload)
        session.add(recipe)
        saved.append(recipe)
        existing.add(name)
    session.commit()
    return {"saved": len(saved), "skipped": len(body.recipes) - len(saved),
            "recipes": [_recipe_json(r) for r in saved]}


@app.patch("/api/recipes/{recipe_id}")
def update_recipe(
    recipe_id: int,
    body: RecipePatch,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    recipe = _owned_recipe(session, user, recipe_id)
    if body.name is not None:
        recipe.name = body.name
    if body.clear_rating:
        recipe.rating = None
    elif body.rating is not None:
        recipe.rating = body.rating
    if body.notes is not None:
        recipe.notes = body.notes
    if body.times_cooked is not None:
        recipe.times_cooked = body.times_cooked
    elif body.cooked:
        # Never below zero -- an undo on a recipe never cooked is a no-op, not
        # a negative count.
        recipe.times_cooked = max(0, (recipe.times_cooked or 0) + body.cooked)
    session.commit()
    return _recipe_json(recipe)


@app.delete("/api/recipes/{recipe_id}")
def delete_recipe(
    recipe_id: int,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, bool]:
    recipe = _owned_recipe(session, user, recipe_id)
    session.delete(recipe)
    session.commit()
    return {"ok": True}


@app.post("/api/recipes/delete-many")
def delete_recipes(
    body: DeleteRecipesRequest,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Delete a batch, ignoring anything that is not yours or not there."""
    rows = session.scalars(
        select(Recipe).where(Recipe.user_id == user.id,
                             Recipe.id.in_(body.ids))).all()
    for row in rows:
        session.delete(row)
    session.commit()
    return {"deleted": len(rows), "asked": len(body.ids)}


@app.post("/api/prices/manual")
def manual_price(
    body: ManualPrice,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Record a price you saw yourself.

    Stored alongside scraped readings with source "manual", so a correction
    shows up in the history and the graph rather than being lost.
    """
    today = date.today().isoformat()
    existing = session.scalar(
        select(PriceRecord).where(
            PriceRecord.user_id == user.id,
            PriceRecord.food == body.food,
            PriceRecord.observed_on == today,
            PriceRecord.source == "manual",
        )
    )
    record = existing or PriceRecord(
        user_id=user.id, food=body.food, observed_on=today, source="manual")
    record.price = body.price
    record.pack = body.pack
    record.per_kg = (body.price / (body.pack / 1000)) if body.pack else None
    record.basis = "gross"
    record.store = body.store
    record.matched_name = ""
    if existing is None:
        session.add(record)
    session.commit()
    return {"ok": True, "food": body.food, "price": body.price,
            "pack": body.pack, "perKg": record.per_kg, "date": today}


# --------------------------------------------------------------------------
# Product catalogue
# --------------------------------------------------------------------------

@app.get("/api/catalogue")
def catalogue(
    q: str = Query("", max_length=200),
    store: Optional[str] = Query(None, max_length=32),
    on_special: bool = Query(False),
    sort: str = Query("relevance"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Search the products this server has already seen. No network access."""
    return pricing.catalogue_search(
        session, query=q, store=store, on_special=on_special,
        sort=sort, limit=limit, offset=offset)


@app.get("/api/alternatives")
def alternatives(
    food: str = Query(..., min_length=1, max_length=200),
    query: str = Query("", max_length=200),
    pack: Optional[float] = Query(None, ge=1, le=50000),
    limit: int = Query(12, ge=1, le=40),
    live: bool = Query(False),
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Other products that would do for a shopping line, best first.

    The resolver's own ranking, so the order here is the order it would have
    picked in -- which is the useful thing to see when you disagree with what
    it picked. Prices come from the catalogue; `live` goes to the store for
    anything it has not seen, which is slower and rate limited.
    """
    term = (query or food).strip()
    if live:
        found = pricing.search(session, term, limit=36, store="woolworths")
        products = found.get("products") or []
    else:
        products = pricing.catalogue_search(
            session, query=term, store="woolworths", limit=40).get("products") or []
        if not products:
            plain = food.split(",")[0]
            for attempt in (plain, " ".join(plain.split()[:2])):
                products = (pricing.catalogue_search(
                    session, query=attempt, store="woolworths",
                    limit=40).get("products") or [])
                if products:
                    break

    wanted = f"{term} {food}"
    ranked = sorted(
        (p for p in products if p.get("pack_price")),
        key=lambda p: resolve.score(p, wanted, pack), reverse=True)[:limit]

    return {
        "food": food,
        "query": term,
        "count": len(ranked),
        "products": [{
            **p,
            # So the page can show why one is above another rather than just
            # asserting an order.
            "match": round(resolve.name_similarity(wanted, p.get("name", "")), 2),
            "flags": [note for note, hit in (
                ("a prepared form", resolve.form_penalty(wanted, p.get("name", ""))),
                ("a cut you did not ask for",
                 resolve.processed_penalty(wanted, p.get("name", ""))),
                ("a mixture", resolve.mixture_penalty(wanted, p.get("name", ""))),
                ("contradicts the plan",
                 resolve.conflict_penalty(wanted, p.get("name", ""))),
            ) if hit],
        } for p in ranked],
    }


@app.get("/api/catalogue/stats")
def catalogue_stats(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """How many products have accumulated, per store."""
    return pricing.catalogue_stats(session)


@app.post("/api/plans/{plan_id}/shop-items", status_code=status.HTTP_201_CREATED)
def add_shop_item(
    plan_id: int,
    body: ShopItemIn,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """Put a product on the shopping list.

    Accepts either a catalogue product (store + stockcode), in which case its
    name, pack size and current price come along, or a plain food name typed by
    hand.
    """
    plan = _owned_plan(session, user, plan_id)
    data = dict(plan.data or {})
    shop = dict(data.get("shop") or {})
    prices = dict(data.get("prices") or {})

    product = None
    if body.store and body.stockcode:
        product = session.scalar(
            select(Product).where(Product.store == body.store,
                                  Product.stockcode == body.stockcode))
        if product is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND,
                                "That product is not in the catalogue.")

    name = (body.food or (product.name if product else "")).strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Give the item a name.")
    if name in shop:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f'"{name}" is already on the list.')

    pack = body.pack or (product.pack_g if product else None)
    shop[name] = {
        "aisle": body.aisle,
        "woo": body.query or (product.name if product else name),
        "pack": pack,
        "grams": body.grams or pack,
        "packsNeeded": 1,
    }
    if product:
        shop[name]["store"] = product.store
        shop[name]["stockcode"] = product.stockcode
        shop[name]["image"] = product.image or ""
        shop[name]["url"] = product.url or ""

    # Price it now, not on the next refresh. Adding something and getting a
    # blank row is what made this feel broken -- "add" should produce a
    # finished line.
    if product and product.pack_price and pack:
        prices.setdefault(name, []).append({
            "price": product.pack_price,
            "pack": pack,
            "date": date.today().isoformat(),
            "store": product.store,
            "source": "catalogue",
            "matched": product.name,
            "url": product.url or "",
        })
        if product.image:
            shop[name]["image"] = product.image
    else:
        # No catalogue product -- typed by hand, or scanned and only known to
        # the open food database. Look it up once so the line is still costed.
        try:
            found = pricing.compare_food(
                session, name, shop[name]["woo"], target_pack_g=pack)
            best = None
            if found.get("cheapest"):
                best = found["byStore"][found["cheapest"]]
            else:
                for candidate in found.get("byStore", {}).values():
                    if candidate.get("status") == "ok" and candidate.get("price"):
                        best = candidate
                        break
            if best and best.get("price"):
                prices.setdefault(name, []).append({
                    "price": best["price"],
                    "pack": best.get("pack") or pack,
                    "date": date.today().isoformat(),
                    "store": best.get("store") or "",
                    "source": "lookup-on-add",
                    "matched": best.get("matched_name") or "",
                    "url": best.get("url") or "",
                })
                if not shop[name].get("pack"):
                    shop[name]["pack"] = best.get("pack")
                if best.get("image"):
                    shop[name]["image"] = best["image"]
        except Exception:  # noqa: BLE001 -- the item is added either way
            session.rollback()

    data["shop"] = shop
    data["prices"] = prices
    plan.data = data
    session.commit()
    return {"ok": True, "food": name, "item": shop[name]}


@app.delete("/api/plans/{plan_id}/shop-items/{food}")
def remove_shop_item(
    plan_id: int,
    food: str,
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, bool]:
    """Take an item off the shopping list, leaving its price history alone."""
    plan = _owned_plan(session, user, plan_id)
    data = dict(plan.data or {})
    shop = dict(data.get("shop") or {})
    if food not in shop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not on the list.")
    del shop[food]
    data["shop"] = shop
    data["got"] = [g for g in (data.get("got") or []) if g != food]
    plan.data = data
    session.commit()
    return {"ok": True}


@app.get("/api/price-cache")
def price_cache(
    user: User = Depends(auth.current_user),
    session: Session = Depends(get_session),
) -> Dict[str, Any]:
    """What the shared cache holds, and whether a store is paused."""
    return pricing.cache_status(session)


@app.get("/api/version")
def version() -> Dict[str, Any]:
    """What build this server is running.

    The point of this is being able to confirm an update actually reached a
    phone, rather than trusting that it did.
    """
    return {"version": APP_VERSION, "builtAt": BUILD_STAMP}


@app.get("/api/cuisines")
def cuisines(user: User = Depends(auth.current_user)) -> Dict[str, Any]:
    """Themes the recipe builder can work to."""
    return {"cuisines": recipes.cuisine_names()}


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "stores": list(stores.ALL_STORES)}


@app.get("/api/trickle")
def trickle_status(
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Whether the slow background catalogue top-up is running."""
    return trickle.status()


@app.get("/api/auto-price")
def auto_price_status(
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """When the weekly price check last ran, and when it next will."""
    return autoprice.status()


@app.post("/api/auto-price/run")
def auto_price_now(
    user: User = Depends(auth.current_user),
) -> Dict[str, Any]:
    """Run the weekly check now, for everyone, rather than waiting for it.

    Reads the catalogue and makes no outbound request, so there is nothing to
    rate limit here beyond the work itself.
    """
    return autoprice.price_everything()


# --------------------------------------------------------------------------
# Frontend -- served from the same origin, so no CORS and no artifact CSP.
# --------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    # Served from the root so its scope is the whole app: a worker registered
    # from /static could only ever control /static. The StaticFiles mount also
    # shadows any route under /static, so this could not live there anyway.
    return FileResponse(
        STATIC_DIR / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/.well-known/assetlinks.json")
def asset_links() -> Any:
    """Proves this site and the Android app belong to the same owner.

    Without this the app opens with a browser address bar across the top; with
    it, it runs full screen like any other app. The fingerprint is of the key
    the APK was signed with, set as TWA_FINGERPRINT.
    """
    fingerprint = os.getenv("TWA_FINGERPRINT", "").strip()
    package = os.getenv("TWA_PACKAGE", "au.com.chronox.shelfplan").strip()
    if not fingerprint:
        return JSONResponse([], status_code=200)
    return JSONResponse([{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": package,
            "sha256_cert_fingerprints": [fingerprint],
        },
    }])


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(STATIC_DIR / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.exception_handler(404)
def not_found(request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return FileResponse(STATIC_DIR / "index.html", status_code=200)
