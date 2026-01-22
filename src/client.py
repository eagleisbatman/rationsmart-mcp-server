"""HTTP client for RationSmart Backend API."""

import os
from typing import Any

import httpx
from pydantic import BaseModel


class BackendConfig(BaseModel):
    """Configuration for backend API connection."""

    base_url: str = "https://ration-smart-backend-production.up.railway.app"
    api_key: str = ""
    timeout: float = 60.0


class RationSmartClient:
    """HTTP client for RationSmart backend API."""

    def __init__(self, config: BackendConfig | None = None):
        self.config = config or BackendConfig(
            base_url=os.getenv("RATIONSMART_BACKEND_URL", "https://ration-smart-backend-production.up.railway.app"),
            api_key=os.getenv("RATIONSMART_API_KEY", ""),
        )
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            headers=self._get_headers(),
        )

    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        return headers

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()

    # ========== Country/Setup Endpoints ==========

    async def get_countries(self) -> list[dict[str, Any]]:
        """Get all available countries."""
        response = await self._client.get("/auth/countries")
        response.raise_for_status()
        return response.json()

    async def get_breeds(self, country_id: str) -> dict[str, Any]:
        """Get breeds available for a country."""
        response = await self._client.get(f"/auth/breeds/{country_id}")
        response.raise_for_status()
        return response.json()

    # ========== Cow Profile Endpoints ==========

    async def create_cow(
        self,
        device_id: str,
        name: str,
        breed: str | None = None,
        body_weight: float = 400.0,
        lactating: bool = True,
        milk_production: float = 10.0,
        target_milk_yield: float | None = None,
        days_in_milk: int = 100,
        parity: int = 2,
        days_of_pregnancy: int = 0,
        milk_fat_percent: float = 4.0,
        milk_protein_percent: float = 3.5,
    ) -> dict[str, Any]:
        """Create a new cow profile."""
        payload = {
            "telegram_user_id": device_id,
            "name": name,
            "breed": breed,
            "body_weight": body_weight,
            "lactating": lactating,
            "milk_production": milk_production,
            "target_milk_yield": target_milk_yield,
            "days_in_milk": days_in_milk,
            "parity": parity,
            "days_of_pregnancy": days_of_pregnancy,
            "milk_fat_percent": milk_fat_percent,
            "milk_protein_percent": milk_protein_percent,
        }
        response = await self._client.post("/cow-profiles/", json=payload)
        response.raise_for_status()
        return response.json()

    async def list_cows(self, device_id: str, include_inactive: bool = False) -> dict[str, Any]:
        """List all cows for a device/user."""
        params = {"include_inactive": include_inactive}
        response = await self._client.get(f"/cow-profiles/user/{device_id}", params=params)
        response.raise_for_status()
        return response.json()

    async def get_cow(self, cow_id: str, device_id: str) -> dict[str, Any]:
        """Get a specific cow profile."""
        params = {"telegram_user_id": device_id}
        response = await self._client.get(f"/cow-profiles/detail/{cow_id}", params=params)
        response.raise_for_status()
        return response.json()

    async def update_cow(
        self,
        cow_id: str,
        device_id: str,
        **updates: Any,
    ) -> dict[str, Any]:
        """Update a cow profile."""
        params = {"telegram_user_id": device_id}
        response = await self._client.put(f"/cow-profiles/{cow_id}", params=params, json=updates)
        response.raise_for_status()
        return response.json()

    async def delete_cow(self, cow_id: str, device_id: str, hard_delete: bool = False) -> dict[str, Any]:
        """Delete a cow profile."""
        params = {"telegram_user_id": device_id, "hard_delete": hard_delete}
        response = await self._client.delete(f"/cow-profiles/{cow_id}", params=params)
        response.raise_for_status()
        return response.json()

    # ========== Feed Endpoints ==========

    async def get_feeds(self, country_id: str) -> list[dict[str, Any]]:
        """Get all feeds for a country."""
        response = await self._client.get(f"/feeds/master-feeds/{country_id}")
        response.raise_for_status()
        return response.json()

    # ========== Diet Generation ==========

    async def generate_diet_for_cow(
        self,
        cow_id: str,
        device_id: str,
        country_id: str,
    ) -> dict[str, Any]:
        """Generate a diet recommendation for a cow.

        Workflow:
        1. Get cow profile
        2. Get feeds for the country
        3. Build cattle_info from cow profile
        4. Call diet-recommendation-working endpoint
        5. Process and return result with diet summary
        """
        import uuid as uuid_module

        # 1. Get cow profile
        cow = await self.get_cow(cow_id, device_id)

        # 2. Get feeds for the country
        feeds = await self.get_feeds(country_id)

        # Build feed selection with prices
        DEFAULT_PRICE = 1.0
        feed_selection = [
            {
                "feed_id": f.get("feed_id") or f.get("id"),
                "price_per_kg": f.get("baseline_price") or DEFAULT_PRICE,
            }
            for f in feeds
            if f.get("feed_id") or f.get("id")
        ]

        if not feed_selection:
            raise ValueError("No feeds available for this country")

        # Build feed names lookup for diet summary
        feed_names_lookup = {}
        for f in feeds:
            feed_id = f.get("feed_id") or f.get("id")
            if feed_id:
                feed_names_lookup[feed_id] = {
                    "english_name": f.get("fd_name") or f.get("name", "Unknown"),
                    "local_name": f.get("local_name"),
                    "fd_type": f.get("fd_type"),
                    "fd_category": f.get("fd_category"),
                }

        # 3. Build cattle_info from cow profile
        # Use target_milk_yield if set, otherwise use current milk_production
        milk_yield = cow.get("milk_production", 10)
        if cow.get("target_milk_yield"):
            milk_yield = cow["target_milk_yield"]

        cattle_info = {
            "body_weight": cow.get("body_weight", 400),
            "breed": cow.get("breed", ""),
            "lactating": cow.get("lactating", True),
            "milk_production": milk_yield,
            "days_in_milk": cow.get("days_in_milk", 100),
            "parity": cow.get("parity", 2),
            "days_of_pregnancy": cow.get("days_of_pregnancy", 0),
            "tp_milk": cow.get("milk_protein_percent", 3.5),
            "fat_milk": cow.get("milk_fat_percent", 4.0),
            "temperature": 25,
            "topography": "Flat",
            "distance": 1,
            "calving_interval": 370,
            "bw_gain": 0.2,
            "bc_score": 3,
        }

        # 4. Call diet-recommendation-working endpoint
        simulation_id = f"mcp-{uuid_module.uuid4().hex[:8]}"
        payload = {
            "simulation_id": simulation_id,
            "user_id": device_id,
            "cattle_info": cattle_info,
            "feed_selection": feed_selection,
        }

        response = await self._client.post("/diet-recommendation-working/", json=payload)
        response.raise_for_status()
        result = response.json()

        # 5. Extract diet summary (morning/evening split)
        diet_summary = self._extract_diet_summary(result, feed_names_lookup)
        total_cost = result.get("total_diet_cost", 0)

        # Add summary to result
        result["diet_summary"] = diet_summary
        result["total_cost_per_day"] = total_cost
        result["currency"] = "INR"

        return result

    def _extract_diet_summary(self, result: dict, feed_names_lookup: dict) -> dict:
        """Extract simplified diet summary with morning/evening split."""
        diet_details = result.get("least_cost_diet", [])

        morning_feeds = []
        evening_feeds = []

        for feed in diet_details:
            feed_id = feed.get("feed_id")
            english_name = feed.get("feed_name", "Unknown")
            local_name = None
            fd_type = None

            if feed_id and feed_id in feed_names_lookup:
                lookup = feed_names_lookup[feed_id]
                english_name = lookup.get("english_name") or english_name
                local_name = lookup.get("local_name")
                fd_type = lookup.get("fd_type")

            qty = feed.get("quantity_kg_per_day", 0)

            feed_item = {
                "name": english_name,
                "english_name": english_name,
                "local_name": local_name,
                "quantity_kg": round(qty, 1),
                "fd_type": fd_type,
            }

            # Split into morning and evening (half each)
            morning_feeds.append({**feed_item, "quantity_kg": round(qty / 2, 1)})
            evening_feeds.append({**feed_item, "quantity_kg": round(qty / 2, 1)})

        return {
            "morning": morning_feeds,
            "evening": evening_feeds,
        }

    # ========== Diet History ==========

    async def save_diet(
        self,
        device_id: str,
        cow_id: str,
        diet_summary: dict[str, Any],
        full_result: dict[str, Any] | None = None,
        name: str = "Generated Diet",
        status: str = "saved",
        is_active: bool = False,
        total_cost: float | None = None,
        currency: str | None = None,
    ) -> dict[str, Any]:
        """Save a diet to history."""
        payload = {
            "telegram_user_id": device_id,
            "cow_profile_id": cow_id,
            "simulation_id": f"mcp-{cow_id[:8]}",
            "name": name,
            "status": status,
            "is_active": is_active,
            "diet_summary": diet_summary,
            "full_result": full_result,
            "total_cost_per_day": total_cost,
            "currency": currency,
        }
        response = await self._client.post("/bot-diet-history/", json=payload)
        response.raise_for_status()
        return response.json()

    async def get_diet_history(
        self,
        device_id: str,
        cow_id: str | None = None,
    ) -> dict[str, Any]:
        """Get diet history for a user/cow."""
        url = f"/bot-diet-history/user/{device_id}"
        params = {}
        if cow_id:
            params["cow_profile_id"] = cow_id
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        return response.json()

    async def get_active_diet(self, cow_id: str, device_id: str) -> dict[str, Any]:
        """Get the active/followed diet for a cow."""
        params = {"telegram_user_id": device_id}
        response = await self._client.get(f"/bot-diet-history/active/{cow_id}", params=params)
        response.raise_for_status()
        return response.json()

    async def follow_diet(self, diet_id: str, device_id: str) -> dict[str, Any]:
        """Mark a diet as being followed."""
        params = {"telegram_user_id": device_id}
        payload = {"status": "following", "is_active": True}
        response = await self._client.put(f"/bot-diet-history/{diet_id}", params=params, json=payload)
        response.raise_for_status()
        return response.json()

    async def unfollow_diet(self, diet_id: str, device_id: str) -> dict[str, Any]:
        """Stop following a diet."""
        params = {"telegram_user_id": device_id}
        payload = {"status": "saved", "is_active": False}
        response = await self._client.put(f"/bot-diet-history/{diet_id}", params=params, json=payload)
        response.raise_for_status()
        return response.json()


# Global client instance
_client: RationSmartClient | None = None


def get_client() -> RationSmartClient:
    """Get or create the global client instance."""
    global _client
    if _client is None:
        _client = RationSmartClient()
    return _client


async def close_client():
    """Close the global client instance."""
    global _client
    if _client is not None:
        await _client.close()
        _client = None
