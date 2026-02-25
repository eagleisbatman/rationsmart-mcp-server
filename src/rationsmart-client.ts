/**
 * RationSmart Backend API Client
 *
 * Wraps the RationSmart FastAPI backend for use by MCP tool handlers.
 * Auth: Bearer token (ff_live_* API key).
 * Identity mapping: GAP device_id → RationSmart telegram_user_id (direct 1:1).
 */

import fetch from 'node-fetch';
import { randomUUID } from 'crypto';

// ===========================================
// Types
// ===========================================

export interface Country {
  id: string;
  name: string;
  country_code: string;
  currency: string;
  is_active: boolean;
}

export interface Breed {
  id: string;
  name: string;
  description?: string;
  sort_order: number;
}

export interface CowProfile {
  id: string;
  telegram_user_id: string;
  name: string;
  breed: string;
  body_weight: number;
  lactating: boolean;
  milk_production: number;
  target_milk_yield: number | null;
  days_in_milk: number;
  parity: number;
  days_of_pregnancy: number;
  milk_fat_percent: number;
  milk_protein_percent: number;
  is_active: boolean;
  created_at: string;
}

export interface CreateCowParams {
  device_id: string;
  name: string;
  breed: string;
  body_weight: number;
  milk_production: number;
  lactating: boolean;
  days_of_pregnancy: number;
}

export interface FeedDetails {
  feed_id: string;
  fd_name: string;
  fd_type: string;
  fd_category: string;
  fd_dm: number;
  fd_cp: number;
  fd_ndf: number;
  fd_ee: number;
  fd_ca: number;
  fd_p: number;
  fd_adf: number;
  fd_lg: number;
  fd_st: number;
  fd_ash: number;
  baseline_price: number;
}

/** CattleInfo for diet-recommendation-working endpoint. */
interface CattleInfo {
  body_weight: number;
  breed: string;
  lactating: boolean;
  milk_production: number;
  days_in_milk: number;
  parity: number;
  days_of_pregnancy: number;
  tp_milk: number;
  fat_milk: number;
  temperature: number;
  topography: string;
  distance: number;
  calving_interval: number;
  bw_gain: number;
  bc_score: number;
}

export interface DietHistoryEntry {
  id: string;
  cow_profile_id: string;
  name: string;
  status: string;
  is_active: boolean;
  diet_summary: Record<string, unknown>;
  total_cost_per_day: number | null;
  currency: string;
  created_at: string;
}

export interface TelegramUser {
  id: string;
  telegram_id: string;
  telegram_username?: string;
  telegram_first_name?: string;
  country_id?: string;
  language_code?: string;
  user_id?: string | null;
}

export interface RationSmartClientConfig {
  baseUrl: string;
  apiKey: string;
  /** Service account user_id for diet-recommendation-working. */
  userId: string;
  /** Default country_id fallback. */
  defaultCountryId: string;
}

// ===========================================
// Client
// ===========================================

export class RationSmartClient {
  private baseUrl: string;
  private apiKey: string;
  private userId: string;
  private defaultCountryId: string;

  // In-memory country cache (refreshed every hour)
  private cachedCountries: Country[] | null = null;
  private cachedCountriesAt = 0;
  private static COUNTRY_CACHE_TTL = 3_600_000; // 1 hour

  constructor(config: RationSmartClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/$/, '');
    this.apiKey = config.apiKey;
    this.userId = config.userId;
    this.defaultCountryId = config.defaultCountryId;
  }

  // ---- HTTP helpers ----

  private getHeaders(): Record<string, string> {
    return {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${this.apiKey}`,
      'User-Agent': 'RationSmart-MCP-Server/1.0.0',
    };
  }

  private async request<T>(
    method: string,
    path: string,
    body?: Record<string, unknown>,
    timeoutMs = 30_000,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    try {
      const response = await fetch(url, {
        method,
        headers: this.getHeaders(),
        body: body ? JSON.stringify(body) : undefined,
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        const errorText = await response.text().catch(() => '');
        // Use process.stderr so it is captured in structured JSON log format by the server
        process.stderr.write(JSON.stringify({
          timestamp: new Date().toISOString(),
          level: 'error',
          service: 'rationsmart-client',
          message: `API error (${response.status})`,
          path,
          detail: errorText.slice(0, 500),
        }) + '\n');
        throw new Error(`RationSmart API error (${response.status})`);
      }

      return (await response.json()) as T;
    } catch (error: unknown) {
      clearTimeout(timeoutId);
      if (error instanceof Error && error.name === 'AbortError') {
        throw new Error('Request timed out');
      }
      throw error;
    }
  }

  // ---- Countries ----

  async getCountries(): Promise<Country[]> {
    const now = Date.now();
    if (this.cachedCountries && now - this.cachedCountriesAt < RationSmartClient.COUNTRY_CACHE_TTL) {
      return this.cachedCountries;
    }
    const countries = await this.request<Country[]>('GET', '/auth/countries');
    this.cachedCountries = countries.filter((c) => c.is_active);
    this.cachedCountriesAt = now;
    return this.cachedCountries;
  }

  async resolveCountry(params: {
    country_name?: string;
    latitude?: number;
    longitude?: number;
  }): Promise<{ country_id: string; country_name: string; currency: string } | null> {
    const countries = await this.getCountries();
    if (countries.length === 0) return null;

    // Match by name (case-insensitive partial match)
    if (params.country_name) {
      const query = params.country_name.toLowerCase();
      const match = countries.find(
        (c) => c.name.toLowerCase() === query || c.country_code.toLowerCase() === query,
      );
      if (match) {
        return { country_id: match.id, country_name: match.name, currency: match.currency };
      }
    }

    // Crude geo-resolve: match by known country bounding boxes
    if (params.latitude != null && params.longitude != null) {
      const geo = this.geoResolveCountry(countries, params.latitude, params.longitude);
      if (geo) {
        return { country_id: geo.id, country_name: geo.name, currency: geo.currency };
      }
    }

    // Fallback: return first active country.
    // This means the user's location or country name did not match any supported country.
    // Log a warning so this can be detected and the country catalog can be extended.
    const fallback = countries[0];
    process.stderr.write(JSON.stringify({
      timestamp: new Date().toISOString(),
      level: 'warn',
      service: 'rationsmart-client',
      message: 'resolveCountry: no match found, falling back to first active country',
      requestedName: params.country_name ?? null,
      lat: params.latitude ?? null,
      lon: params.longitude ?? null,
      fallbackCountry: fallback.name,
    }) + '\n');
    return { country_id: fallback.id, country_name: fallback.name, currency: fallback.currency };
  }

  private geoResolveCountry(countries: Country[], lat: number, lon: number): Country | null {
    // Simple bounding-box lookup for RationSmart active countries
    const BOXES: Record<string, { minLat: number; maxLat: number; minLon: number; maxLon: number }> = {
      BGD: { minLat: 20.5, maxLat: 26.6, minLon: 88.0, maxLon: 92.7 },   // Bangladesh
      ETH: { minLat: 3.0,  maxLat: 15.0, minLon: 33.0, maxLon: 48.0 },   // Ethiopia
      IND: { minLat: 6.5,  maxLat: 35.5, minLon: 68.0, maxLon: 97.5 },   // India
      IDN: { minLat: -11.0, maxLat: 6.1, minLon: 95.0, maxLon: 141.0 },  // Indonesia
      MAR: { minLat: 27.6, maxLat: 35.9, minLon: -13.2, maxLon: -1.0 },  // Morocco
      NPL: { minLat: 26.3, maxLat: 30.5, minLon: 80.0, maxLon: 88.2 },   // Nepal
      PAK: { minLat: 23.6, maxLat: 37.1, minLon: 60.8, maxLon: 77.8 },   // Pakistan
      PHL: { minLat: 4.6,  maxLat: 21.1, minLon: 116.9, maxLon: 126.6 }, // Philippines
      THA: { minLat: 5.6,  maxLat: 20.5, minLon: 97.3, maxLon: 105.6 },  // Thailand
      VNM: { minLat: 8.2,  maxLat: 23.4, minLon: 102.1, maxLon: 109.5 }, // Vietnam
    };
    for (const country of countries) {
      const box = BOXES[country.country_code];
      if (box && lat >= box.minLat && lat <= box.maxLat && lon >= box.minLon && lon <= box.maxLon) {
        return country;
      }
    }
    return null;
  }

  // ---- User (telegram_users upsert — identity bridge) ----

  /**
   * Ensure a user exists in RationSmart's telegram_users table.
   * Idempotent: creates on first call, updates on subsequent calls.
   * Uses telegram_username = "FarmerChat" to identify the source channel.
   */
  async ensureUser(params: {
    deviceId: string;
    name?: string;
    countryId?: string;
    language?: string;
  }): Promise<TelegramUser> {
    return this.request<TelegramUser>('POST', '/telegram-users/', {
      telegram_id: params.deviceId,
      telegram_username: 'FarmerChat',
      telegram_first_name: params.name || 'Farmer',
      ...(params.countryId ? { country_id: params.countryId } : {}),
      ...(params.language ? { language_code: params.language } : {}),
    });
  }

  // ---- Breeds ----

  async listBreeds(countryId: string): Promise<Breed[]> {
    const resp = await this.request<{ success: boolean; breeds: Breed[]; count: number }>(
      'GET',
      `/auth/breeds/${countryId}`,
    );
    return resp.breeds || [];
  }

  // ---- Cow Profiles ----

  async listCows(deviceId: string): Promise<CowProfile[]> {
    const resp = await this.request<{ success: boolean; count: number; cow_profiles: CowProfile[] }>(
      'GET',
      `/cow-profiles/user/${encodeURIComponent(deviceId)}?limit=50`,
    );
    return resp.cow_profiles || [];
  }

  async getCow(cowId: string): Promise<CowProfile> {
    return this.request<CowProfile>('GET', `/cow-profiles/detail/${encodeURIComponent(cowId)}`);
  }

  async createCow(params: CreateCowParams): Promise<CowProfile> {
    const body = {
      telegram_user_id: params.device_id,
      name: params.name,
      breed: params.breed,
      body_weight: params.body_weight,
      lactating: params.lactating,
      milk_production: params.lactating ? params.milk_production : 0,
      target_milk_yield: params.lactating ? params.milk_production * 1.1 : null,
      days_in_milk: 90,
      parity: 2,
      days_of_pregnancy: params.days_of_pregnancy,
      milk_fat_percent: 3.5,
      milk_protein_percent: 3.2,
    };
    return this.request<CowProfile>('POST', '/cow-profiles/', body);
  }

  // ---- Feeds ----

  async getFeeds(countryId: string): Promise<FeedDetails[]> {
    return this.request<FeedDetails[]>('GET', `/master-feeds/?country_id=${encodeURIComponent(countryId)}`);
  }

  // ---- Diet Generation (Multi-step orchestration) ----

  async generateDiet(
    cowId: string,
    countryId: string,
    deviceId: string,
  ): Promise<{ dietId: string; summary: string; totalCost: number; currency: string; feeds: { name: string; quantity_kg: number; cost: number }[] }> {
    // Steps 1 & 2: Fetch cow profile and feed catalog in parallel — they are independent
    const [cow, feeds] = await Promise.all([
      this.getCow(cowId),
      this.getFeeds(countryId),
    ]);

    // Verify ownership — cow must belong to the requesting device
    if (cow.telegram_user_id !== deviceId) {
      throw new Error('Cow not found or access denied');
    }

    if (!feeds || feeds.length === 0) {
      throw new Error('No feed catalog found for this country');
    }

    // Step 3: Build cattle_info from cow profile
    const cattleInfo: CattleInfo = {
      body_weight: cow.body_weight,
      breed: cow.breed,
      lactating: cow.lactating,
      milk_production: cow.milk_production,
      days_in_milk: cow.days_in_milk || 90,
      parity: cow.parity || 2,
      days_of_pregnancy: cow.days_of_pregnancy || 0,
      tp_milk: cow.milk_protein_percent || 3.2,
      fat_milk: cow.milk_fat_percent || 3.5,
      temperature: 25,
      topography: 'Flat',
      distance: 0,
      calving_interval: 365,
      bw_gain: 0,
      bc_score: 3.0,
    };

    // Step 4: Build feed selection (use all feeds with their baseline prices)
    const feedSelection = feeds.map((f) => ({
      feed_id: f.feed_id,
      price_per_kg: f.baseline_price || 1.0,
    }));

    // Step 5: Call optimizer (longer timeout — NSGA-III can be slow)
    const simulationId = `mcp-${randomUUID()}`;
    const optimizerResult = await this.request<Record<string, unknown>>(
      'POST',
      '/animal/diet-recommendation-working/',
      {
        simulation_id: simulationId,
        user_id: this.userId,
        cattle_info: cattleInfo,
        feed_selection: feedSelection,
      },
      60_000, // 60s timeout for optimizer
    );

    // Step 6: Parse optimizer response
    const resultFeeds = this.parseDietFeeds(optimizerResult, feeds);
    const totalCost = resultFeeds.reduce((sum, f) => sum + f.cost, 0);

    // Resolve country for currency
    const countries = await this.getCountries();
    const country = countries.find((c) => c.id === countryId);
    const currency = country?.currency || 'USD';

    // Step 7: Save diet to history
    const dietHistory = await this.request<DietHistoryEntry>(
      'POST',
      '/bot-diet-history/',
      {
        telegram_user_id: deviceId,
        cow_profile_id: cowId,
        simulation_id: simulationId,
        name: `Diet for ${cow.name}`,
        status: 'created',
        is_active: true,
        diet_summary: {
          feeds: resultFeeds,
          total_cost: totalCost,
          currency,
          cow_name: cow.name,
          generated_at: new Date().toISOString(),
        },
        total_cost_per_day: totalCost,
        currency,
      },
    );

    // Build human-readable summary
    const feedLines = resultFeeds.map(
      (f) => `  - ${f.name}: ${f.quantity_kg.toFixed(1)} kg/day (${currency} ${f.cost.toFixed(2)})`,
    );
    const summary = [
      `Diet for ${cow.name} (${cow.breed}, ${cow.body_weight} kg)`,
      `Daily cost: ${currency} ${totalCost.toFixed(2)}`,
      '',
      'Feed plan:',
      ...feedLines,
    ].join('\n');

    return {
      dietId: dietHistory.id,
      summary,
      totalCost,
      currency,
      feeds: resultFeeds,
    };
  }

  private parseDietFeeds(
    result: Record<string, unknown>,
    masterFeeds: FeedDetails[],
  ): { name: string; quantity_kg: number; cost: number }[] {
    const feedMap = new Map(masterFeeds.map((f) => [f.feed_id, f.fd_name]));
    const parsed: { name: string; quantity_kg: number; cost: number }[] = [];

    // The optimizer returns results in various formats; try common patterns
    const solutions = (result as Record<string, unknown>).solutions as unknown[];
    const solution = Array.isArray(solutions) ? solutions[0] : result;

    const feedResults =
      (solution as Record<string, unknown>)?.feed_results ??
      (solution as Record<string, unknown>)?.feeds ??
      (solution as Record<string, unknown>)?.diet_results;

    if (Array.isArray(feedResults)) {
      for (const item of feedResults as Record<string, unknown>[]) {
        const feedId = item.feed_id as string;
        const quantity = (item.quantity_kg ?? item.quantity_as_fed ?? item.quantity ?? 0) as number;
        const cost = (item.cost ?? item.total_cost ?? 0) as number;
        if (quantity > 0) {
          parsed.push({
            name: feedMap.get(feedId) || (item.feed_name as string) || feedId,
            quantity_kg: quantity,
            cost,
          });
        }
      }
    } else {
      // The optimizer returned a response shape we don't recognise.
      // Log the top-level keys so the response format can be diagnosed.
      const topKeys = Object.keys(result).join(', ');
      process.stderr.write(JSON.stringify({
        timestamp: new Date().toISOString(),
        level: 'error',
        service: 'rationsmart-client',
        message: 'parseDietFeeds: unrecognised optimizer response shape — feed_results/feeds/diet_results not found',
        topLevelKeys: topKeys,
        solutionKeys: solution ? Object.keys(solution as object).join(', ') : 'none',
      }) + '\n');
    }

    return parsed;
  }

  // ---- Diet Follow-up ----

  /**
   * Fetch a single diet history entry by ID.
   * Used to verify ownership before mutating operations.
   */
  private async getDietById(dietId: string): Promise<DietHistoryEntry & { telegram_user_id?: string }> {
    return this.request<DietHistoryEntry & { telegram_user_id?: string }>(
      'GET',
      `/bot-diet-history/${encodeURIComponent(dietId)}`,
    );
  }

  /**
   * Verify that a diet belongs to the requesting device.
   * Falls back to cow-profile ownership check when telegram_user_id is not on the diet record.
   */
  private async verifyDietOwnership(deviceId: string, dietId: string): Promise<void> {
    const diet = await this.getDietById(dietId);
    // Prefer direct telegram_user_id on the diet entry if the API returns it
    if (diet.telegram_user_id !== undefined) {
      if (diet.telegram_user_id !== deviceId) {
        throw new Error('Diet not found or access denied');
      }
      return;
    }
    // Fallback: verify via the associated cow's owner
    const cow = await this.getCow(diet.cow_profile_id);
    if (cow.telegram_user_id !== deviceId) {
      throw new Error('Diet not found or access denied');
    }
  }

  async followDiet(deviceId: string, dietId: string): Promise<string> {
    await this.verifyDietOwnership(deviceId, dietId);

    // Update the diet history entry to status='following', is_active=true
    await this.request<Record<string, unknown>>(
      'PUT',
      `/bot-diet-history/${encodeURIComponent(dietId)}`,
      {
        status: 'following',
        is_active: true,
      },
    );

    // Create initial follow-up log entry for weekly check-in
    const nextWeek = new Date();
    nextWeek.setDate(nextWeek.getDate() + 7);

    await this.request<Record<string, unknown>>(
      'POST',
      '/bot-follow-up-logs/',
      {
        telegram_user_id: deviceId,
        diet_history_id: dietId,
        scheduled_at: nextWeek.toISOString(),
        status: 'pending',
      },
    );

    return 'You are now following this diet. I will check in with you next week to see how it is going.';
  }

  async unfollowDiet(deviceId: string, dietId: string): Promise<string> {
    await this.verifyDietOwnership(deviceId, dietId);

    // Mark diet as archived
    await this.request<Record<string, unknown>>(
      'PUT',
      `/bot-diet-history/${encodeURIComponent(dietId)}`,
      {
        status: 'archived',
        is_active: false,
      },
    );

    return 'Diet follow-up has been stopped. You can start a new feed plan anytime.';
  }

  // ---- Schedule & History ----

  async getDietSchedule(deviceId: string, cowId: string): Promise<string> {
    const active = await this.request<DietHistoryEntry | null>(
      'GET',
      `/bot-diet-history/active/${encodeURIComponent(cowId)}?telegram_user_id=${encodeURIComponent(deviceId)}`,
    );

    if (!active || !active.diet_summary) {
      return 'No active diet found for this cow. Would you like to generate a new feed plan?';
    }

    const summary = active.diet_summary as Record<string, unknown>;
    const feeds = summary.feeds as { name: string; quantity_kg: number; cost: number }[] | undefined;
    const cowName = (summary.cow_name as string) || 'your cow';
    const currency = (summary.currency as string) || '';

    if (!feeds || feeds.length === 0) {
      return `Active diet found for ${cowName} but no feed details available.`;
    }

    const lines = [
      `Daily feeding schedule for ${cowName}:`,
      '',
      'Morning (06:00):',
      ...feeds
        .filter((f) => f.name.toLowerCase().includes('forage') || f.name.toLowerCase().includes('grass') || f.name.toLowerCase().includes('hay') || f.name.toLowerCase().includes('straw') || f.name.toLowerCase().includes('silage'))
        .map((f) => `  - ${f.name}: ${(f.quantity_kg / 2).toFixed(1)} kg`),
      '',
      'Afternoon (12:00):',
      ...feeds
        .filter((f) => !f.name.toLowerCase().includes('forage') && !f.name.toLowerCase().includes('grass') && !f.name.toLowerCase().includes('hay') && !f.name.toLowerCase().includes('straw') && !f.name.toLowerCase().includes('silage'))
        .map((f) => `  - ${f.name}: ${f.quantity_kg.toFixed(1)} kg`),
      '',
      'Evening (18:00):',
      ...feeds
        .filter((f) => f.name.toLowerCase().includes('forage') || f.name.toLowerCase().includes('grass') || f.name.toLowerCase().includes('hay') || f.name.toLowerCase().includes('straw') || f.name.toLowerCase().includes('silage'))
        .map((f) => `  - ${f.name}: ${(f.quantity_kg / 2).toFixed(1)} kg`),
      '',
      `Total daily cost: ${currency} ${feeds.reduce((s, f) => s + (f.cost || 0), 0).toFixed(2)}`,
    ];

    return lines.join('\n');
  }

  async listDietHistory(deviceId: string, cowId: string): Promise<string> {
    const resp = await this.request<{ success: boolean; count: number; diets: DietHistoryEntry[] }>(
      'GET',
      `/bot-diet-history/cow/${encodeURIComponent(cowId)}?telegram_user_id=${encodeURIComponent(deviceId)}&include_archived=true`,
    );

    const diets = resp.diets || [];
    if (diets.length === 0) {
      return 'No diet history found for this cow.';
    }

    const lines = diets.map((d, idx) => {
      const date = new Date(d.created_at).toLocaleDateString();
      const status = d.is_active ? '(active)' : `(${d.status})`;
      const cost = d.total_cost_per_day ? ` - ${d.currency || ''} ${d.total_cost_per_day.toFixed(2)}/day` : '';
      return `${idx + 1}. ${d.name} ${status} - ${date}${cost}`;
    });

    return `Diet history:\n${lines.join('\n')}`;
  }
}
