"""RationSmart MCP Server - AI-powered cow diet management."""

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv
from mcp.server import Server
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.requests import Request

from src.client import get_client, close_client

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("rationsmart-mcp")

# Create MCP server instance
server = Server("rationsmart")

COUNTRY_CODE_OVERRIDES = {
    "vn": "vnm",
    "in": "ind",
    "et": "eth",
    "id": "idn",
    "ph": "phl",
    "pk": "pak",
    "bd": "bgd",
    "np": "npl",
    "ke": "ken",
    "tz": "tza",
    "ug": "uga",
}

SERVER_INFO = {"name": "RationSmart Tools", "version": "0.1.0"}

TOOL_ALIASES = {
    "get_countries": "rationsmart.countries.list",
    "get_breeds": "rationsmart.breeds.list",
    "resolve_location": "rationsmart.location.resolve",
    "resolve_country_id": "rationsmart.countries.resolve",
    "create_cow": "rationsmart.cows.create",
    "list_cows": "rationsmart.cows.list",
    "get_cow": "rationsmart.cows.get",
    "update_cow": "rationsmart.cows.update",
    "delete_cow": "rationsmart.cows.delete",
    "generate_diet": "rationsmart.diets.generate",
    "get_diet_schedule": "rationsmart.diets.schedule.get",
    "get_diet_history": "rationsmart.diets.history.list",
    "follow_diet": "rationsmart.diets.follow",
    "stop_following_diet": "rationsmart.diets.unfollow",
}

TOOL_TITLES = {
    "rationsmart.countries.list": "List Countries",
    "rationsmart.breeds.list": "List Breeds",
    "rationsmart.location.resolve": "Resolve Location",
    "rationsmart.countries.resolve": "Resolve Country ID",
    "rationsmart.cows.create": "Create Cow Profile",
    "rationsmart.cows.list": "List Cow Profiles",
    "rationsmart.cows.get": "Get Cow Details",
    "rationsmart.cows.update": "Update Cow Profile",
    "rationsmart.cows.delete": "Delete Cow Profile",
    "rationsmart.diets.generate": "Generate Diet",
    "rationsmart.diets.schedule.get": "Get Diet Schedule",
    "rationsmart.diets.history.list": "List Diet History",
    "rationsmart.diets.follow": "Follow Diet",
    "rationsmart.diets.unfollow": "Stop Following Diet",
}


# ========== Tool Definitions ==========

TOOLS = [
    # User/Setup tools
    Tool(
        name="rationsmart.countries.list",
        description=(
            "List supported countries for onboarding (id, name, currency).\n"
            "Use when the user needs to select or confirm their country.\n"
            "Read-only.\n"
            "Returns all active countries."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="rationsmart.breeds.list",
        description=(
            "List cattle breeds available for a country.\n"
            "Use after the user selects a country to show breed options.\n"
            "Read-only.\n"
            "Requires a valid country_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "country_id": {
                    "type": "string",
                    "description": "The country UUID from get_countries",
                },
            },
            "required": ["country_id"],
        },
    ),
    Tool(
        name="rationsmart.location.resolve",
        description=(
            "Resolve country and region from latitude/longitude via backend geocoding.\n"
            "Use when you only have GPS coordinates.\n"
            "Read-only (calls external geocoding).\n"
            "Requires latitude and longitude."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "latitude": {"type": "number", "description": "Latitude"},
                "longitude": {"type": "number", "description": "Longitude"},
            },
            "required": ["latitude", "longitude"],
        },
    ),
    Tool(
        name="rationsmart.countries.resolve",
        description=(
            "Resolve backend country_id from country code/name or latitude/longitude.\n"
            "Use before diet generation when you do not have a country_id.\n"
            "Read-only.\n"
            "Falls back to the first active country if no match is found."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "country_code": {"type": "string", "description": "ISO country code (2 or 3 letters)"},
                "country_name": {"type": "string", "description": "Country name"},
                "latitude": {"type": "number", "description": "Latitude"},
                "longitude": {"type": "number", "description": "Longitude"},
            },
            "required": [],
        },
    ),
    # Cow tools
    Tool(
        name="rationsmart.cows.create",
        description=(
            "Create a new cow profile for a farmer.\n"
            "Use when onboarding a cow for diet planning.\n"
            "Writes to the database.\n"
            "Requires device_id and name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Unique device/user identifier for the farmer",
                },
                "name": {
                    "type": "string",
                    "description": "Name of the cow (e.g., 'Lakshmi', 'Ganga')",
                },
                "breed": {
                    "type": "string",
                    "description": "Breed of the cow",
                },
                "body_weight": {
                    "type": "number",
                    "description": "Body weight in kg (typically 300-600 kg)",
                    "default": 400,
                },
                "lactating": {
                    "type": "boolean",
                    "description": "Is the cow currently lactating?",
                    "default": True,
                },
                "milk_production": {
                    "type": "number",
                    "description": "Current daily milk production in liters",
                    "default": 10,
                },
                "target_milk_yield": {
                    "type": "number",
                    "description": "Target milk yield in liters/day (optional)",
                },
                "days_in_milk": {
                    "type": "integer",
                    "description": "Days since calving",
                    "default": 100,
                },
                "parity": {
                    "type": "integer",
                    "description": "Number of times the cow has calved",
                    "default": 2,
                },
                "days_of_pregnancy": {
                    "type": "integer",
                    "description": "Days of pregnancy (0 if not pregnant)",
                    "default": 0,
                },
            },
            "required": ["device_id", "name"],
        },
    ),
    Tool(
        name="rationsmart.cows.list",
        description=(
            "List cow profiles for a farmer.\n"
            "Use when showing the farmer's herd or selecting a cow.\n"
            "Read-only.\n"
            "Requires device_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Unique device/user identifier for the farmer",
                },
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="rationsmart.cows.get",
        description=(
            "Get details for a specific cow profile.\n"
            "Use when viewing or editing a cow.\n"
            "Read-only.\n"
            "Requires device_id and cow_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {
                    "type": "string",
                    "description": "Unique device/user identifier",
                },
                "cow_id": {
                    "type": "string",
                    "description": "The cow's unique ID",
                },
            },
            "required": ["device_id", "cow_id"],
        },
    ),
    Tool(
        name="rationsmart.cows.update",
        description=(
            "Update fields on a cow profile.\n"
            "Use when the farmer edits weight, milk, or status.\n"
            "Writes to the database.\n"
            "Requires device_id and cow_id; send only changed fields."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "cow_id": {"type": "string", "description": "The cow's unique ID"},
                "name": {"type": "string"},
                "body_weight": {"type": "number"},
                "milk_production": {"type": "number"},
                "target_milk_yield": {"type": "number"},
                "lactating": {"type": "boolean"},
                "days_in_milk": {"type": "integer"},
                "parity": {"type": "integer"},
                "days_of_pregnancy": {"type": "integer"},
            },
            "required": ["device_id", "cow_id"],
        },
    ),
    Tool(
        name="rationsmart.cows.delete",
        description=(
            "Delete or deactivate a cow profile.\n"
            "Use when the farmer removes a cow.\n"
            "Writes to the database; can be permanent.\n"
            "Requires device_id and cow_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "cow_id": {"type": "string", "description": "The cow's unique ID"},
                "permanent": {"type": "boolean", "description": "Permanently delete?", "default": False},
            },
            "required": ["device_id", "cow_id"],
        },
    ),
    # Diet tools
    Tool(
        name="rationsmart.diets.generate",
        description=(
            "Generate a diet recommendation for a cow.\n"
            "Use after cow details and a country are known.\n"
            "Writes a diet record if save_diet is true.\n"
            "Requires device_id, cow_id, and a country (id/code or lat/long)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "cow_id": {"type": "string", "description": "The cow's unique ID"},
                "country_id": {"type": "string", "description": "Country ID for feed availability"},
                "country_code": {"type": "string", "description": "ISO country code (2 or 3 letters)"},
                "country_name": {"type": "string", "description": "Country name"},
                "latitude": {"type": "number", "description": "Latitude"},
                "longitude": {"type": "number", "description": "Longitude"},
                "save_diet": {"type": "boolean", "description": "Save for later reference", "default": True},
            },
            "required": ["device_id", "cow_id"],
        },
    ),
    Tool(
        name="rationsmart.diets.schedule.get",
        description=(
            "Get the active diet feeding schedule for a cow.\n"
            "Use when showing morning/evening instructions.\n"
            "Read-only.\n"
            "Requires device_id and cow_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "cow_id": {"type": "string", "description": "The cow's unique ID"},
            },
            "required": ["device_id", "cow_id"],
        },
    ),
    Tool(
        name="rationsmart.diets.history.list",
        description=(
            "List diet history for a farmer (optionally per cow).\n"
            "Use when showing past diets or analytics.\n"
            "Read-only.\n"
            "Requires device_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "cow_id": {"type": "string", "description": "Optional: filter to specific cow"},
            },
            "required": ["device_id"],
        },
    ),
    Tool(
        name="rationsmart.diets.follow",
        description=(
            "Mark a diet as actively followed.\n"
            "Use when the farmer starts a plan.\n"
            "Writes to the database and enables reminders.\n"
            "Requires device_id and diet_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "diet_id": {"type": "string", "description": "The diet's unique ID"},
            },
            "required": ["device_id", "diet_id"],
        },
    ),
    Tool(
        name="rationsmart.diets.unfollow",
        description=(
            "Stop following a diet.\n"
            "Use when the farmer ends a plan.\n"
            "Writes to the database.\n"
            "Requires device_id and diet_id."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "diet_id": {"type": "string", "description": "The diet's unique ID"},
            },
            "required": ["device_id", "diet_id"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all available tools."""
    return TOOLS


def _format_diet_schedule(diet_summary: dict) -> str:
    """Format diet summary into readable schedule."""
    lines = []
    for period in ["morning", "evening"]:
        feeds = diet_summary.get(period, [])
        if feeds:
            lines.append(f"{period.title()} Feeding:")
            for feed in feeds:
                name = feed.get("english_name") or feed.get("name", "Unknown")
                qty = feed.get("quantity_kg", 0)
                if qty >= 1:
                    lines.append(f"  - {name}: {qty:.1f} kg")
                elif qty > 0:
                    lines.append(f"  - {name}: {qty * 1000:.0f} grams")
            lines.append("")
    return "\n".join(lines).strip() or "No schedule available"


def _normalize_name(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _normalize_code(value: str | None) -> str:
    if not value:
        return ""
    return value.strip().lower()


async def _resolve_country_id(
    client: Any,
    *,
    country_code: str | None = None,
    country_name: str | None = None,
) -> str | None:
    countries = await client.get_countries()
    normalized_name = _normalize_name(country_name)
    code = _normalize_code(country_code)
    mapped_code = COUNTRY_CODE_OVERRIDES.get(code, code)

    match = None
    if normalized_name:
        match = next(
            (c for c in countries if _normalize_name(c.get("name")) == normalized_name),
            None,
        )
    if not match and mapped_code:
        match = next(
            (c for c in countries if _normalize_code(c.get("country_code")) == mapped_code),
            None,
        )
    if not match and normalized_name:
        match = next(
            (
                c
                for c in countries
                if normalized_name in _normalize_name(c.get("name"))
                or _normalize_name(c.get("name")) in normalized_name
            ),
            None,
        )
    if not match:
        match = next((c for c in countries if c.get("is_active")), None)
    return match.get("id") if match else None


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    client = get_client()
    name = TOOL_ALIASES.get(name, name)

    try:
        # ========== User/Setup Tools ==========
        if name == "rationsmart.countries.list":
            countries = await client.get_countries()
            lines = ["Available countries:\n"]
            for c in countries:
                lines.append(f"- {c['name']} (ID: {c['id']}, Currency: {c.get('currency', 'N/A')})")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "rationsmart.breeds.list":
            country_id = arguments.get("country_id")
            if not country_id:
                return [TextContent(type="text", text="Error: country_id is required")]
            result = await client.get_breeds(country_id)
            breeds = result.get("breeds", [])
            if not breeds:
                return [TextContent(type="text", text="No breeds found.")]
            lines = ["Available breeds:\n"]
            for b in breeds:
                lines.append(f"- {b['name']}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "rationsmart.location.resolve":
            latitude = arguments.get("latitude")
            longitude = arguments.get("longitude")
            if latitude is None or longitude is None:
                return [TextContent(type="text", text="Error: latitude and longitude are required")]
            resolved = await client.resolve_location(latitude, longitude)
            return [TextContent(type="text", text=json.dumps(resolved))]

        elif name == "rationsmart.countries.resolve":
            country_code = arguments.get("country_code")
            country_name = arguments.get("country_name")
            latitude = arguments.get("latitude")
            longitude = arguments.get("longitude")

            if not (country_code or country_name):
                if latitude is not None and longitude is not None:
                    resolved = await client.resolve_location(latitude, longitude)
                    country_code = resolved.get("country_code")
                    country_name = resolved.get("country_name")
                else:
                    return [TextContent(type="text", text="Error: provide country_code/country_name or latitude/longitude")]

            country_id = await _resolve_country_id(
                client, country_code=country_code, country_name=country_name
            )
            if not country_id:
                return [TextContent(type="text", text="Error: unable to resolve country_id")]
            payload = {
                "country_id": country_id,
                "country_code": country_code,
                "country_name": country_name,
            }
            return [TextContent(type="text", text=json.dumps(payload))]

        # ========== Cow Tools ==========
        elif name == "rationsmart.cows.create":
            device_id = arguments.get("device_id")
            cow_name = arguments.get("name")
            if not device_id or not cow_name:
                return [TextContent(type="text", text="Error: device_id and name are required")]

            result = await client.create_cow(
                device_id=device_id,
                name=cow_name,
                breed=arguments.get("breed"),
                body_weight=arguments.get("body_weight", 400),
                lactating=arguments.get("lactating", True),
                milk_production=arguments.get("milk_production", 10),
                target_milk_yield=arguments.get("target_milk_yield"),
                days_in_milk=arguments.get("days_in_milk", 100),
                parity=arguments.get("parity", 2),
                days_of_pregnancy=arguments.get("days_of_pregnancy", 0),
            )
            return [TextContent(
                type="text",
                text=f"Created cow profile:\n"
                     f"- Name: {result['name']}\n"
                     f"- ID: {result['id']}\n"
                     f"- Breed: {result.get('breed', 'Not specified')}\n"
                     f"- Weight: {result['body_weight']} kg\n"
                     f"- Milk: {result['milk_production']} L/day"
            )]

        elif name == "rationsmart.cows.list":
            device_id = arguments.get("device_id")
            if not device_id:
                return [TextContent(type="text", text="Error: device_id is required")]

            result = await client.list_cows(device_id=device_id)
            cows = result.get("cow_profiles", [])
            if not cows:
                return [TextContent(type="text", text="No cows found.")]

            lines = [f"Found {len(cows)} cow(s):\n"]
            for cow in cows:
                status = "Lactating" if cow.get("lactating") else "Dry"
                milk = f"{cow.get('milk_production', 0)} L/day" if cow.get("lactating") else "N/A"
                lines.append(
                    f"- {cow['name']} (ID: {cow['id']})\n"
                    f"  Breed: {cow.get('breed', 'Unknown')} | {status} | Milk: {milk}"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "rationsmart.cows.get":
            device_id = arguments.get("device_id")
            cow_id = arguments.get("cow_id")
            if not device_id or not cow_id:
                return [TextContent(type="text", text="Error: device_id and cow_id are required")]

            cow = await client.get_cow(cow_id=cow_id, device_id=device_id)
            target = f"{cow.get('target_milk_yield')} L/day" if cow.get("target_milk_yield") else "Not set"
            return [TextContent(
                type="text",
                text=f"Cow: {cow['name']}\n"
                     f"ID: {cow['id']}\n"
                     f"Breed: {cow.get('breed', 'Not specified')}\n"
                     f"Weight: {cow['body_weight']} kg\n"
                     f"Lactating: {'Yes' if cow['lactating'] else 'No'}\n"
                     f"Milk: {cow['milk_production']} L/day\n"
                     f"Target: {target}\n"
                     f"Days in Milk: {cow.get('days_in_milk', 0)}\n"
                     f"Parity: {cow.get('parity', 0)}\n"
                     f"Pregnancy: {cow.get('days_of_pregnancy', 0)} days"
            )]

        elif name == "rationsmart.cows.update":
            device_id = arguments.get("device_id")
            cow_id = arguments.get("cow_id")
            if not device_id or not cow_id:
                return [TextContent(type="text", text="Error: device_id and cow_id are required")]

            updates = {k: v for k, v in arguments.items()
                       if k not in ["device_id", "cow_id"] and v is not None}
            if not updates:
                return [TextContent(type="text", text="No updates provided.")]

            result = await client.update_cow(cow_id=cow_id, device_id=device_id, **updates)
            return [TextContent(type="text", text=f"Updated {result['name']} successfully.")]

        elif name == "rationsmart.cows.delete":
            device_id = arguments.get("device_id")
            cow_id = arguments.get("cow_id")
            if not device_id or not cow_id:
                return [TextContent(type="text", text="Error: device_id and cow_id are required")]

            result = await client.delete_cow(
                cow_id=cow_id,
                device_id=device_id,
                hard_delete=arguments.get("permanent", False),
            )
            return [TextContent(type="text", text=result.get("message", "Cow deleted."))]

        # ========== Diet Tools ==========
        elif name == "rationsmart.diets.generate":
            device_id = arguments.get("device_id")
            cow_id = arguments.get("cow_id")
            country_id = arguments.get("country_id")
            if not all([device_id, cow_id]):
                return [TextContent(type="text", text="Error: device_id and cow_id are required")]

            if not country_id:
                country_code = arguments.get("country_code")
                country_name = arguments.get("country_name")
                latitude = arguments.get("latitude")
                longitude = arguments.get("longitude")
                if not (country_code or country_name):
                    if latitude is not None and longitude is not None:
                        resolved = await client.resolve_location(latitude, longitude)
                        country_code = resolved.get("country_code")
                        country_name = resolved.get("country_name")
                if country_code or country_name:
                    country_id = await _resolve_country_id(
                        client, country_code=country_code, country_name=country_name
                    )

            if not country_id:
                return [TextContent(type="text", text="Error: country_id or country_code/latitude+longitude is required")]

            cow = await client.get_cow(cow_id=cow_id, device_id=device_id)
            cow_name = cow.get("name", "the cow")

            result = await client.generate_diet_for_cow(
                cow_id=cow_id, device_id=device_id, country_id=country_id
            )

            # Save diet
            diet_id = None
            if arguments.get("save_diet", True):
                diet_summary = result.get("diet_summary", {})
                saved = await client.save_diet(
                    device_id=device_id,
                    cow_id=cow_id,
                    diet_summary=diet_summary,
                    full_result=result,
                    name=f"Diet for {cow_name}",
                    total_cost=result.get("total_cost_per_day") or result.get("total_diet_cost"),
                    currency=result.get("currency"),
                )
                diet_id = saved.get("id")

            # Format response
            lines = [f"Diet for {cow_name}:\n"]

            diet_summary = result.get("diet_summary", {})
            if diet_summary:
                lines.append(_format_diet_schedule(diet_summary))
            else:
                least_cost = result.get("least_cost_diet", [])
                if least_cost:
                    lines.append("Feeds:")
                    for feed in least_cost:
                        lines.append(f"  - {feed.get('feed_name')}: {feed.get('quantity_kg_per_day', 0):.2f} kg/day")

            cost = result.get("total_cost_per_day") or result.get("total_diet_cost")
            if cost:
                currency = result.get("currency", "INR")
                lines.append(f"\nDaily Cost: {currency} {cost:.2f}")

            if diet_id:
                lines.append(f"\nDiet saved (ID: {diet_id})")
                lines.append("Use 'rationsmart.diets.follow' to start following this diet.")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "rationsmart.diets.schedule.get":
            device_id = arguments.get("device_id")
            cow_id = arguments.get("cow_id")
            if not device_id or not cow_id:
                return [TextContent(type="text", text="Error: device_id and cow_id are required")]

            try:
                diet = await client.get_active_diet(cow_id=cow_id, device_id=device_id)
                cow = await client.get_cow(cow_id=cow_id, device_id=device_id)

                schedule = _format_diet_schedule(diet.get("diet_summary", {}))
                cost = diet.get("total_cost_per_day")
                cost_line = f"\nDaily Cost: {diet.get('currency', 'INR')} {cost:.2f}" if cost else ""

                return [TextContent(
                    type="text",
                    text=f"Schedule for {cow.get('name', 'cow')}:\n\n{schedule}{cost_line}"
                )]
            except Exception as e:
                if "404" in str(e) or "not found" in str(e).lower():
                    return [TextContent(
                        type="text",
                        text="No active diet. Generate a diet and use 'rationsmart.diets.follow' to start following it."
                    )]
                raise

        elif name == "rationsmart.diets.history.list":
            device_id = arguments.get("device_id")
            if not device_id:
                return [TextContent(type="text", text="Error: device_id is required")]

            result = await client.get_diet_history(
                device_id=device_id,
                cow_id=arguments.get("cow_id"),
            )
            diets = result.get("diets", [])
            if not diets:
                return [TextContent(type="text", text="No diet history.")]

            lines = [f"Found {len(diets)} diet(s):\n"]
            for d in diets:
                active = " (ACTIVE)" if d.get("is_active") else ""
                cost = d.get("total_cost_per_day")
                cost_str = f", {d.get('currency', 'INR')} {cost:.2f}/day" if cost else ""
                lines.append(f"- {d.get('name', 'Unnamed')}{active}\n  ID: {d['id']}{cost_str}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "rationsmart.diets.follow":
            device_id = arguments.get("device_id")
            diet_id = arguments.get("diet_id")
            if not device_id or not diet_id:
                return [TextContent(type="text", text="Error: device_id and diet_id are required")]

            result = await client.follow_diet(diet_id=diet_id, device_id=device_id)
            return [TextContent(
                type="text",
                text=f"Now following: {result.get('name', 'diet')}\n"
                     "Follow-up reminders are now enabled."
            )]

        elif name == "rationsmart.diets.unfollow":
            device_id = arguments.get("device_id")
            diet_id = arguments.get("diet_id")
            if not device_id or not diet_id:
                return [TextContent(type="text", text="Error: device_id and diet_id are required")]

            await client.unfollow_diet(diet_id=diet_id, device_id=device_id)
            return [TextContent(type="text", text="Stopped following the diet.")]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except Exception as e:
        logger.error(f"Tool {name} failed: {e}")
        return [TextContent(type="text", text=f"Error: {e}")]


async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "ok", "service": "rationsmart-mcp"})


async def list_tools_endpoint(request: Request) -> JSONResponse:
    """List all available tools."""
    tools_data = [
        {
            "name": tool.name,
            "title": TOOL_TITLES.get(tool.name, tool.name),
            "description": tool.description,
            "inputSchema": tool.inputSchema,
        }
        for tool in TOOLS
    ]
    return JSONResponse({"tools": tools_data})


async def call_tool_endpoint(request: Request) -> JSONResponse:
    """Call a tool with given arguments."""
    try:
        body = await request.json()
        tool_name = body.get("name")
        arguments = body.get("arguments", {})

        if not tool_name:
            return JSONResponse(
                {"error": "Missing 'name' field"},
                status_code=400,
            )

        # Call the tool
        result = await call_tool(tool_name, arguments)

        # Extract text content from result
        if result and len(result) > 0:
            return JSONResponse({
                "success": True,
                "result": result[0].text if hasattr(result[0], 'text') else str(result[0]),
            })
        else:
            return JSONResponse({
                "success": True,
                "result": "No response",
            })

    except json.JSONDecodeError:
        return JSONResponse(
            {"error": "Invalid JSON body"},
            status_code=400,
        )
    except Exception as e:
        logger.error(f"Tool call failed: {e}")
        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )


def _wants_sse(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/event-stream" in accept.lower()


def _jsonrpc_response(request: Request, payload: dict, status_code: int = 200) -> Response:
    if _wants_sse(request):
        data = f"data: {json.dumps(payload)}\n\n"
        return Response(data, media_type="text/event-stream", status_code=status_code)
    return JSONResponse(payload, status_code=status_code)


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any | None = None) -> dict:
    error = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


async def mcp_endpoint(request: Request) -> Response:
    """JSON-RPC 2.0 MCP endpoint."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return _jsonrpc_response(
            request,
            _jsonrpc_error(None, -32700, "Parse error"),
            status_code=400,
        )

    if not isinstance(body, dict):
        return _jsonrpc_response(
            request,
            _jsonrpc_error(None, -32600, "Invalid Request"),
            status_code=400,
        )

    request_id = body.get("id")
    if body.get("jsonrpc") != "2.0":
        return _jsonrpc_response(
            request,
            _jsonrpc_error(request_id, -32600, "Invalid Request"),
            status_code=400,
        )

    method = body.get("method")
    params = body.get("params") or {}

    if method == "initialize":
        protocol_version = params.get("protocolVersion", "2024-11-05")
        result = {
            "protocolVersion": protocol_version,
            "capabilities": {"tools": {"list": True, "call": True}},
            "serverInfo": SERVER_INFO,
        }
        return _jsonrpc_response(request, {"jsonrpc": "2.0", "id": request_id, "result": result})

    if method == "tools/list":
        result = {
            "tools": [
                {
                    "name": tool.name,
                    "title": TOOL_TITLES.get(tool.name, tool.name),
                    "description": tool.description,
                    "inputSchema": tool.inputSchema,
                }
                for tool in TOOLS
            ]
        }
        return _jsonrpc_response(request, {"jsonrpc": "2.0", "id": request_id, "result": result})

    if method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if not tool_name:
            return _jsonrpc_response(
                request,
                _jsonrpc_error(request_id, -32602, "Missing tool name"),
                status_code=400,
            )
        content_list = await call_tool(tool_name, arguments)
        content = []
        for item in content_list:
            text = item.text if hasattr(item, "text") else str(item)
            content.append({"type": "text", "text": text})
        is_error = bool(content) and content[0].get("text", "").lower().startswith("error:")
        result = {"content": content, "isError": is_error}
        return _jsonrpc_response(request, {"jsonrpc": "2.0", "id": request_id, "result": result})

    return _jsonrpc_response(
        request,
        _jsonrpc_error(request_id, -32601, "Method not found"),
        status_code=404,
    )


# Create Starlette app with routes
app = Starlette(
    debug=False,
    routes=[
        Route("/", health_check, methods=["GET"]),
        Route("/health", health_check, methods=["GET"]),
        Route("/tools", list_tools_endpoint, methods=["GET"]),
        Route("/tools/call", call_tool_endpoint, methods=["POST"]),
        Route("/mcp", mcp_endpoint, methods=["POST"]),
    ],
)


def main():
    """Entry point for the MCP server."""
    import uvicorn

    port = int(os.getenv("PORT", "8080"))
    logger.info(f"Starting RationSmart MCP Server on port {port}...")

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
