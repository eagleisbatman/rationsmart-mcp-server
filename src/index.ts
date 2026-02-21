/**
 * RationSmart MCP Server
 *
 * Exposes 9 MCP tools for dairy cattle nutrition: country resolution, breed listing,
 * cow profile CRUD, diet optimization, follow-up management, and history.
 *
 * Consumed by rationsmart-flow.ts in AI Services via the tool executor.
 * Response formats MUST match the parsers in rationsmart-flow.ts.
 */

import 'dotenv/config';
import express from 'express';
import cors from 'cors';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';
import { RationSmartClient } from './rationsmart-client.js';

// ===========================================
// Structured Logger
// ===========================================
const logger = {
  _log(level: string, message: string, context?: Record<string, unknown>) {
    const entry: Record<string, unknown> = {
      timestamp: new Date().toISOString(),
      level,
      service: 'rationsmart-mcp-server',
      message,
    };
    if (context && Object.keys(context).length > 0) entry.context = context;
    process.stdout.write(JSON.stringify(entry) + '\n');
  },
  info(message: string, context?: Record<string, unknown>) { this._log('info', message, context); },
  warn(message: string, context?: Record<string, unknown>) { this._log('warn', message, context); },
  error(message: string, context?: Record<string, unknown>) { this._log('error', message, context); },
};

// ===========================================
// In-memory Rate Limiter (100 req/min per IP)
// ===========================================
const RATE_LIMIT_WINDOW_MS = 60_000;
const RATE_LIMIT_MAX = 100;
const rateLimitMap = new Map<string, { count: number; resetTime: number }>();

function rateLimiter(req: express.Request, res: express.Response, next: express.NextFunction) {
  const ip = req.ip || req.socket.remoteAddress || 'unknown';
  const now = Date.now();
  let entry = rateLimitMap.get(ip);

  if (!entry || now > entry.resetTime) {
    entry = { count: 1, resetTime: now + RATE_LIMIT_WINDOW_MS };
    rateLimitMap.set(ip, entry);
  } else {
    entry.count++;
  }

  if (entry.count > RATE_LIMIT_MAX) {
    const retryAfter = Math.ceil((entry.resetTime - now) / 1000);
    res.set('Retry-After', String(retryAfter));
    logger.warn('Rate limit exceeded', { ip, count: entry.count });
    res.status(429).json({ error: 'Too many requests. Please try again later.', retryAfterSeconds: retryAfter });
    return;
  }
  next();
}

// Periodic cleanup of expired rate limit entries
setInterval(() => {
  const now = Date.now();
  for (const [ip, entry] of rateLimitMap) {
    if (now > entry.resetTime) rateLimitMap.delete(ip);
  }
}, RATE_LIMIT_WINDOW_MS);

// ===========================================
// Express App
// ===========================================
const app = express();

app.use(express.json());
app.use(cors({
  origin: process.env.ALLOWED_ORIGINS?.split(',') || '*',
  exposedHeaders: ['Mcp-Session-Id'],
  allowedHeaders: ['Content-Type', 'mcp-session-id', 'Authorization', 'x-api-key', 'X-Farm-Latitude', 'X-Farm-Longitude'],
}));

// Apply rate limiting to all non-health endpoints
app.use((req, res, next) => {
  if (req.path === '/health') return next();
  rateLimiter(req, res, next);
});

// ===========================================
// Environment Variables
// ===========================================
const RATIONSMART_API_URL = process.env.RATIONSMART_API_URL || '';
const RATIONSMART_API_KEY = process.env.RATIONSMART_API_KEY || '';
const RATIONSMART_USER_ID = process.env.RATIONSMART_USER_ID || '';
const RATIONSMART_COUNTRY_ID = process.env.RATIONSMART_COUNTRY_ID || '';
const PORT = process.env.PORT || 3010;

if (!RATIONSMART_API_URL || !RATIONSMART_API_KEY) {
  logger.warn('RATIONSMART_API_URL and RATIONSMART_API_KEY are not set. Server will start but MCP tools will not work.');
}

// Initialize client (only if credentials provided)
const client = (RATIONSMART_API_URL && RATIONSMART_API_KEY)
  ? new RationSmartClient({
      baseUrl: RATIONSMART_API_URL,
      apiKey: RATIONSMART_API_KEY,
      userId: RATIONSMART_USER_ID,
      defaultCountryId: RATIONSMART_COUNTRY_ID,
    })
  : null;

// ===========================================
// Health Check
// ===========================================
app.get('/health', (_req, res) => {
  res.json({
    status: 'healthy',
    service: 'rationsmart-mcp-server',
    timestamp: new Date().toISOString(),
    version: '1.0.0',
    apiConfigured: !!(RATIONSMART_API_URL && RATIONSMART_API_KEY),
  });
});

// ===========================================
// Root Info
// ===========================================
app.get('/', (_req, res) => {
  res.json({
    service: 'RationSmart MCP Server',
    version: '1.0.0',
    description: 'Dairy cattle nutrition optimization — cow profiles, breed selection, and diet generation',
    endpoints: { health: '/health', mcp: '/mcp (POST)' },
    tools: [
      { name: 'rationsmart.countries.resolve', description: 'Resolve country from name or coordinates' },
      { name: 'rationsmart.breeds.list', description: 'List cattle breeds for a country' },
      { name: 'rationsmart.cows.list', description: 'List user cow profiles' },
      { name: 'rationsmart.cows.create', description: 'Create a cow profile' },
      { name: 'rationsmart.diets.generate', description: 'Generate optimized diet for a cow' },
      { name: 'rationsmart.diets.follow', description: 'Start following a diet' },
      { name: 'rationsmart.diets.unfollow', description: 'Stop following a diet' },
      { name: 'rationsmart.diets.schedule.get', description: 'Get daily feeding schedule' },
      { name: 'rationsmart.diets.history.list', description: 'List diet history for a cow' },
    ],
  });
});

// ===========================================
// MCP Authentication Middleware
// ===========================================
function authenticateMcp(req: express.Request, res: express.Response, next: express.NextFunction) {
  const apiKey = req.headers['x-api-key'] as string | undefined;
  const validKey = process.env.MCP_API_KEY || process.env.API_KEY;
  if (!validKey) { next(); return; }
  if (!apiKey || apiKey !== validKey) {
    logger.warn('Authentication failed', { ip: req.ip, hasKey: !!apiKey });
    res.status(401).json({ error: 'Authentication required' });
    return;
  }
  next();
}

// ===========================================
// Helper: error response
// ===========================================
function errorResponse(text: string) {
  return { content: [{ type: 'text' as const, text }], isError: true };
}

function textResponse(text: string) {
  return { content: [{ type: 'text' as const, text }] };
}

// ===========================================
// MCP Endpoint
// ===========================================
app.post('/mcp', authenticateMcp, async (req, res) => {
  const accept = req.headers.accept || '';
  if (!accept.includes('application/json') || !accept.includes('text/event-stream')) {
    req.headers.accept = 'application/json, text/event-stream';
  }

  try {
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined, // Stateless
    });

    const server = new McpServer({
      name: 'rationsmart-feed-formulation',
      version: '1.0.0',
      description: 'Dairy cattle nutrition optimization — cow profiles, breed selection, and diet generation',
    });

    // =========================================================
    // TOOL 1: rationsmart.countries.resolve
    // =========================================================

    server.registerTool(
      'rationsmart.countries.resolve',
      {
        title: 'Resolve Country',
        description: `Resolve the user's country for feed catalog access.
TRIGGERS: Internal — called at start of feed/diet flow.
RETURNS: country_id, country_name, currency.
COVERAGE: Countries with RationSmart feed catalogs.`,
        inputSchema: z.object({
          country_name: z.string().optional().describe('Country name (e.g., "Ethiopia", "Kenya", "India")'),
          latitude: z.number().min(-90).max(90).optional().describe('Latitude for geo-based resolution'),
          longitude: z.number().min(-180).max(180).optional().describe('Longitude for geo-based resolution'),
        }).strict(),
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.countries.resolve called', { country_name: input.country_name, lat: input.latitude, lon: input.longitude });

          if (!client) return errorResponse('Feed service is not configured. Try again in a moment.');

          const result = await client.resolveCountry({
            country_name: input.country_name,
            latitude: input.latitude,
            longitude: input.longitude,
          });

          if (!result) return errorResponse('Could not resolve country. Feed catalogs may not be available for your region.');

          // Response format: JSON string — parsed by parseJsonFromText() in rationsmart-flow.ts
          return textResponse(JSON.stringify(result));
        } catch (error: unknown) {
          logger.error('Error in rationsmart.countries.resolve', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse(`Could not resolve country. ${error instanceof Error ? error.message : 'Try again in a moment.'}`);
        }
      },
    );

    // =========================================================
    // TOOL 2: rationsmart.breeds.list
    // =========================================================

    server.registerTool(
      'rationsmart.breeds.list',
      {
        title: 'List Breeds',
        description: `List available dairy cattle breeds for a country.
TRIGGERS: Internal — called during cow profile creation.
RETURNS: List of breed names.
COVERAGE: Per-country breed catalogs.`,
        inputSchema: z.object({
          country_id: z.string().min(1).describe('Country UUID from rationsmart.countries.resolve'),
        }).strict(),
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.breeds.list called', { country_id: input.country_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const breeds = await client.listBreeds(input.country_id);

          if (breeds.length === 0) return textResponse('No breeds found for this country.');

          // Response format: "- BreedName" per line — parsed by parseBreeds() in rationsmart-flow.ts
          const lines = breeds.map((b) => `- ${b.name}`);
          return textResponse(lines.join('\n'));
        } catch (error: unknown) {
          logger.error('Error in rationsmart.breeds.list', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse('Could not load breeds. Try again in a moment.');
        }
      },
    );

    // =========================================================
    // TOOL 3: rationsmart.cows.list
    // =========================================================

    server.registerTool(
      'rationsmart.cows.list',
      {
        title: 'List Cow Profiles',
        description: `List cow profiles belonging to a user.
TRIGGERS: "my cows", "show my cows", beginning of feed flow.
RETURNS: List of cow names and IDs. Empty if no cows.
COVERAGE: All users.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
        }).strict(),
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.cows.list called', { device_id: input.device_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const cows = await client.listCows(input.device_id);

          if (cows.length === 0) return textResponse('');

          // Response format: "- CowName (ID: uuid)" per line — parsed by parseCowList() in rationsmart-flow.ts
          const lines = cows.map((c) => `- ${c.name} (ID: ${c.id})`);
          return textResponse(lines.join('\n'));
        } catch (error: unknown) {
          logger.error('Error in rationsmart.cows.list', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse('Could not load cow profiles. Try again in a moment.');
        }
      },
    );

    // =========================================================
    // TOOL 4: rationsmart.cows.create
    // =========================================================

    server.registerTool(
      'rationsmart.cows.create',
      {
        title: 'Create Cow Profile',
        description: `Create a new dairy cow profile for a user.
TRIGGERS: "add a cow", "new cow", user has no existing cows.
RETURNS: Created cow profile with ID.
COVERAGE: All RationSmart-supported countries.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
          name: z.string().min(1).max(50).describe('Name for the cow'),
          breed: z.string().min(1).describe('Breed name from rationsmart.breeds.list'),
          body_weight: z.number().min(20).max(2000).describe('Body weight in kg'),
          milk_production: z.number().min(0).max(100).describe('Daily milk production in liters (0 if dry)'),
          lactating: z.boolean().describe('Whether the cow is currently lactating'),
          days_of_pregnancy: z.number().int().min(0).max(285).describe('Days of pregnancy (0 if not pregnant)'),
        }).strict(),
        annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.cows.create called', { device_id: input.device_id, name: input.name, breed: input.breed });

          if (!client) return errorResponse('Feed service is not configured.');

          const cow = await client.createCow({
            device_id: input.device_id,
            name: input.name,
            breed: input.breed,
            body_weight: input.body_weight,
            milk_production: input.milk_production,
            lactating: input.lactating,
            days_of_pregnancy: input.days_of_pregnancy,
          });

          // Response format: text containing "ID: uuid" — parsed by parseIdFromText() in rationsmart-flow.ts
          // Note: cow.name comes from user input, so place the ID at the very start to avoid injection
          return textResponse(`ID: ${cow.id} — Created cow profile '${cow.name}'`);
        } catch (error: unknown) {
          logger.error('Error in rationsmart.cows.create', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse(`Could not create cow profile. ${error instanceof Error ? error.message : 'Try again in a moment.'}`);
        }
      },
    );

    // =========================================================
    // TOOL 5: rationsmart.diets.generate
    // =========================================================

    server.registerTool(
      'rationsmart.diets.generate',
      {
        title: 'Generate Diet',
        description: `Generate an optimized least-cost diet recommendation for a dairy cow.
TRIGGERS: "feed plan", "diet recommendation", "what should I feed".
RETURNS: Optimized daily feed plan with quantities, costs, and nutrient balance.
COVERAGE: Countries with RationSmart feed catalogs.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
          cow_id: z.string().min(1).describe('Cow profile ID'),
          country_id: z.string().min(1).describe('Country UUID from rationsmart.countries.resolve'),
        }).strict(),
        annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: false, openWorldHint: true },
      },
      async (input) => {
        try {
          logger.info('rationsmart.diets.generate called', { device_id: input.device_id, cow_id: input.cow_id, country_id: input.country_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const result = await client.generateDiet(input.cow_id, input.country_id, input.device_id);

          // Response format: summary text containing "Diet saved (ID: uuid)" — parsed by parseDietId() in rationsmart-flow.ts
          return textResponse(`${result.summary}\n\nDiet saved (ID: ${result.dietId})`);
        } catch (error: unknown) {
          logger.error('Error in rationsmart.diets.generate', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse(`Could not generate diet. ${error instanceof Error ? error.message : 'Try again in a moment.'}`);
        }
      },
    );

    // =========================================================
    // TOOL 6: rationsmart.diets.follow
    // =========================================================

    server.registerTool(
      'rationsmart.diets.follow',
      {
        title: 'Follow Diet',
        description: `Start following a diet recommendation, enabling weekly check-ins.
TRIGGERS: User confirms "yes" after diet generation.
RETURNS: Confirmation with follow-up schedule.
COVERAGE: Users with diet recommendations.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
          diet_id: z.string().min(1).describe('Diet recommendation ID from rationsmart.diets.generate'),
        }).strict(),
        annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.diets.follow called', { device_id: input.device_id, diet_id: input.diet_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const message = await client.followDiet(input.device_id, input.diet_id);
          return textResponse(message);
        } catch (error: unknown) {
          logger.error('Error in rationsmart.diets.follow', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse('Could not start diet follow-up. Try again in a moment.');
        }
      },
    );

    // =========================================================
    // TOOL 7: rationsmart.diets.unfollow
    // =========================================================

    server.registerTool(
      'rationsmart.diets.unfollow',
      {
        title: 'Unfollow Diet',
        description: `Stop following a diet and disable weekly check-ins.
TRIGGERS: "stop diet", "cancel follow-up".
RETURNS: Confirmation.
COVERAGE: Users with active diet follow-ups.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
          diet_id: z.string().min(1).describe('Active diet ID to stop following'),
        }).strict(),
        annotations: { readOnlyHint: false, destructiveHint: true, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.diets.unfollow called', { device_id: input.device_id, diet_id: input.diet_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const message = await client.unfollowDiet(input.device_id, input.diet_id);
          return textResponse(message);
        } catch (error: unknown) {
          logger.error('Error in rationsmart.diets.unfollow', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse('Could not stop diet follow-up. Try again in a moment.');
        }
      },
    );

    // =========================================================
    // TOOL 8: rationsmart.diets.schedule.get
    // =========================================================

    server.registerTool(
      'rationsmart.diets.schedule.get',
      {
        title: 'Get Feeding Schedule',
        description: `Get the daily feeding schedule for a cow's active diet.
TRIGGERS: "feeding schedule", "when to feed", "daily plan".
RETURNS: Time-based feeding schedule with quantities.
COVERAGE: Cows with active diet recommendations.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
          cow_id: z.string().min(1).describe('Cow profile ID'),
        }).strict(),
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.diets.schedule.get called', { device_id: input.device_id, cow_id: input.cow_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const schedule = await client.getDietSchedule(input.device_id, input.cow_id);
          return textResponse(schedule);
        } catch (error: unknown) {
          logger.error('Error in rationsmart.diets.schedule.get', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse('Could not load feeding schedule. Try again in a moment.');
        }
      },
    );

    // =========================================================
    // TOOL 9: rationsmart.diets.history.list
    // =========================================================

    server.registerTool(
      'rationsmart.diets.history.list',
      {
        title: 'List Diet History',
        description: `List diet recommendation history for a cow.
TRIGGERS: "diet history", "past diets", "previous feed plans".
RETURNS: List of diets with dates, status, and cost.
COVERAGE: Users with cow profiles.`,
        inputSchema: z.object({
          device_id: z.string().min(1).describe('GAP device ID identifying the user'),
          cow_id: z.string().min(1).describe('Cow profile ID'),
        }).strict(),
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
      },
      async (input) => {
        try {
          logger.info('rationsmart.diets.history.list called', { device_id: input.device_id, cow_id: input.cow_id });

          if (!client) return errorResponse('Feed service is not configured.');

          const history = await client.listDietHistory(input.device_id, input.cow_id);
          return textResponse(history);
        } catch (error: unknown) {
          logger.error('Error in rationsmart.diets.history.list', { error: error instanceof Error ? error.message : String(error) });
          return errorResponse('Could not load diet history. Try again in a moment.');
        }
      },
    );

    // =========================================================
    // Connect and handle request
    // =========================================================
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);

  } catch (error: unknown) {
    logger.error('MCP endpoint error', { error: error instanceof Error ? error.message : String(error) });
    res.status(500).json({
      jsonrpc: '2.0',
      error: {
        code: -32603,
        message: 'Internal server error',
        data: error instanceof Error ? error.message : 'Unknown error',
      },
      id: null,
    });
  }
});

// ===========================================
// Start Server
// ===========================================
const HOST = '0.0.0.0';
const httpServer = app.listen(Number(PORT), HOST, () => {
  logger.info('Server started', {
    host: HOST,
    port: PORT,
    version: '1.0.0',
    apiConfigured: !!(RATIONSMART_API_URL && RATIONSMART_API_KEY),
    tools: [
      'rationsmart.countries.resolve',
      'rationsmart.breeds.list',
      'rationsmart.cows.list',
      'rationsmart.cows.create',
      'rationsmart.diets.generate',
      'rationsmart.diets.follow',
      'rationsmart.diets.unfollow',
      'rationsmart.diets.schedule.get',
      'rationsmart.diets.history.list',
    ],
  });
});

// ===========================================
// Graceful Shutdown
// ===========================================
function gracefulShutdown(signal: string) {
  logger.info('Shutdown signal received', { signal });
  const forceTimeout = setTimeout(() => {
    logger.error('Forced shutdown after 10s timeout', { signal });
    process.exit(1);
  }, 10_000);
  forceTimeout.unref();
  httpServer.close(() => {
    logger.info('HTTP server closed gracefully');
    process.exit(0);
  });
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

process.on('unhandledRejection', (reason) => {
  logger.error('Unhandled rejection', { reason: String(reason) });
});

process.on('uncaughtException', (error) => {
  logger.error('Uncaught exception', { error: error.message, stack: error.stack });
  process.exit(1);
});
