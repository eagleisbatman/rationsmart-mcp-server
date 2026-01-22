"""RationSmart MCP Server - AI-powered cow diet management."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

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


# ========== Tool Definitions ==========

TOOLS = [
    # User/Setup tools
    Tool(
        name="get_countries",
        description="Get list of available countries for onboarding. Returns country IDs, names, and currencies. Use this when a farmer needs to select their country.",
        inputSchema={
            "type": "object",
            "properties": {},
            "required": [],
        },
    ),
    Tool(
        name="get_breeds",
        description="Get available cattle breeds for a specific country. Use this after the farmer selects their country, to help them identify their cow's breed.",
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
    # Cow tools
    Tool(
        name="create_cow",
        description="Create a new cow profile for a farmer. Collects basic cow information like name, breed, weight, milk production, etc.",
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
        name="list_cows",
        description="List all cows owned by a farmer. Returns cow names, IDs, and basic info.",
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
        name="get_cow",
        description="Get detailed information about a specific cow.",
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
        name="update_cow",
        description="Update a cow's profile. Only provide fields that need to be changed.",
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
        name="delete_cow",
        description="Delete/deactivate a cow profile.",
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
        name="generate_diet",
        description="Generate an optimized diet recommendation for a cow based on its profile. Creates a balanced, cost-effective feeding plan.",
        inputSchema={
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "Unique device/user identifier"},
                "cow_id": {"type": "string", "description": "The cow's unique ID"},
                "country_id": {"type": "string", "description": "Country ID for feed availability"},
                "save_diet": {"type": "boolean", "description": "Save for later reference", "default": True},
            },
            "required": ["device_id", "cow_id", "country_id"],
        },
    ),
    Tool(
        name="get_diet_schedule",
        description="Get the feeding schedule for a cow's current active diet. Shows morning and evening feeding instructions.",
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
        name="get_diet_history",
        description="Get history of diets generated for a farmer's cows.",
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
        name="follow_diet",
        description="Mark a diet as being actively followed. Enables follow-up reminders.",
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
        name="stop_following_diet",
        description="Stop following a diet.",
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


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Handle tool calls."""
    client = get_client()

    try:
        # ========== User/Setup Tools ==========
        if name == "get_countries":
            countries = await client.get_countries()
            lines = ["Available countries:\n"]
            for c in countries:
                lines.append(f"- {c['name']} (ID: {c['id']}, Currency: {c.get('currency', 'N/A')})")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_breeds":
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

        # ========== Cow Tools ==========
        elif name == "create_cow":
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

        elif name == "list_cows":
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
                    f"- {cow['name']} (ID: {cow['id'][:8]}...)\n"
                    f"  Breed: {cow.get('breed', 'Unknown')} | {status} | Milk: {milk}"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_cow":
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

        elif name == "update_cow":
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

        elif name == "delete_cow":
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
        elif name == "generate_diet":
            device_id = arguments.get("device_id")
            cow_id = arguments.get("cow_id")
            country_id = arguments.get("country_id")
            if not all([device_id, cow_id, country_id]):
                return [TextContent(type="text", text="Error: device_id, cow_id, and country_id are required")]

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
                lines.append(f"\nDiet saved (ID: {diet_id[:8]}...)")
                lines.append("Use 'follow_diet' to start following this diet.")

            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "get_diet_schedule":
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
                        text="No active diet. Generate a diet and use 'follow_diet' to start following it."
                    )]
                raise

        elif name == "get_diet_history":
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
                lines.append(f"- {d.get('name', 'Unnamed')}{active}\n  ID: {d['id'][:8]}...{cost_str}")
            return [TextContent(type="text", text="\n".join(lines))]

        elif name == "follow_diet":
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

        elif name == "stop_following_diet":
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


async def run_server():
    """Run the MCP server."""
    logger.info("Starting RationSmart MCP Server...")

    async with stdio_server() as (read_stream, write_stream):
        try:
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
        finally:
            await close_client()


def main():
    """Entry point for the MCP server."""
    asyncio.run(run_server())


if __name__ == "__main__":
    main()
