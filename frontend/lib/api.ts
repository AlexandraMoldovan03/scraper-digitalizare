/**
 * API client pentru AgencyIntel.
 *
 * Toate request-urile folosesc URL-uri relative proxied prin Next.js rewrites
 * (configurate în next.config.js) spre http://127.0.0.1:8000.
 * Evită problemele CORS fără să atingem backend-ul.
 */

import { clearAuth, getToken } from './auth';
import type {
  City,
  Source,
  Client,
  ClientCreate,
  MarketListing,
  OpportunityFeedItem,
  GenerateOpportunitiesResult,
  Organization,
  ScrapeJob,
  LatestJobStatus,
  AllSourcesStatus,
  MultiJobResponse,
} from './types';

export interface ListingFilters {
  city_id?: number;
  zone?: string;
  rooms?: number;
  min_price?: number;
  max_price?: number;
  max_price_per_m2?: number;
  min_surface?: number;
  max_surface?: number;
  data_quality?: string;
  source_slug?: string;
  property_type?: string;     // apartment | house | land | commercial
  transaction_type?: string;  // sale | rent
  seller_type?: string;       // private | agency | developer
  locality?: string;
  q?: string;
  new_days?: number;
  sort?: string;
  order?: string;
  limit?: number;
  offset?: number;
}

export interface ListingsSummary {
  total: number;
  new_7d: number;
  avg_price_eur: number | null;
  avg_price_per_m2: number | null;
  by_seller_type: Record<string, number>;
  by_property_type: Record<string, number>;
}

function buildQueryString(params: ListingFilters): string {
  const entries = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '');
  if (!entries.length) return '';
  return '?' + entries.map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`).join('&');
}

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const token = getToken();

  const res = await fetch(path, {
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
    ...options,
  });

  // Sesiune expirată sau invalidată → logout automat
  if (res.status === 401) {
    clearAuth();
    if (typeof window !== 'undefined') {
      window.location.href = '/login';
    }
    throw new Error('Sesiune expirată');
  }

  if (!res.ok) {
    const errorText = await res.text().catch(() => res.statusText);
    throw new Error(`API ${res.status}: ${errorText}`);
  }

  return res.json() as Promise<T>;
}

export const api = {
  // ── Auth ──────────────────────────────────────────────────────────────────
  logout: () =>
    fetchAPI<{ message: string }>('/api/v1/auth/logout', { method: 'POST' }),

  me: () =>
    fetchAPI<{ id: number; email: string; full_name: string; role: string }>(
      '/api/v1/auth/me'
    ),

  // ── Health ────────────────────────────────────────────────────────────────
  health: () =>
    fetchAPI<{ status: string; database: number }>('/health/db'),

  // ── Market ────────────────────────────────────────────────────────────────
  cities: () =>
    fetchAPI<City[]>('/api/v1/market/cities'),

  sources: () =>
    fetchAPI<Source[]>('/api/v1/market/sources'),

  listings: (params?: ListingFilters) => {
    const qs = params ? buildQueryString(params) : '';
    return fetchAPI<MarketListing[]>(`/api/v1/market/listings${qs}`);
  },

  listingsSummary: (params?: ListingFilters) => {
    const qs = params ? buildQueryString(params) : '';
    return fetchAPI<ListingsSummary>(`/api/v1/market/listings/summary${qs}`);
  },

  zones: (cityId: number) =>
    fetchAPI<string[]>('/api/v1/market/zones?city_id=' + cityId),

  refreshImages: (limit = 20) =>
    fetchAPI<{ updated: number; skipped: number; message: string }>(
      `/api/v1/market/listings/refresh-images?limit=${limit}`,
      { method: 'POST' }
    ),

  // ── Clients ───────────────────────────────────────────────────────────────
  clients: () =>
    fetchAPI<Client[]>('/api/v1/clients/'),

  createClient: (data: ClientCreate) =>
    fetchAPI<Client>('/api/v1/clients/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // ── Opportunities ─────────────────────────────────────────────────────────
  opportunitiesFeed: () =>
    fetchAPI<OpportunityFeedItem[]>(
      '/api/v1/opportunities/feed'
    ),

  generateOpportunities: () =>
    fetchAPI<GenerateOpportunitiesResult>(
      '/api/v1/opportunities/generate',
      { method: 'POST' }
    ),

  // ── Organizations ─────────────────────────────────────────────────────────
  organizations: () =>
    fetchAPI<Organization[]>('/api/v1/organizations/'),

  // ── Scraping ──────────────────────────────────────────────────────────────
  /** Declanșează un job pentru o sursă specifică. Returnează ScrapeJob. */
  triggerScrape: (source = 'publi24') =>
    fetchAPI<ScrapeJob>('/api/v1/scraping/jobs', {
      method: 'POST',
      body: JSON.stringify({ source }),
    }),

  /** Declanșează joburi pentru toate sursele active (source=all). */
  triggerScrapeAll: () =>
    fetchAPI<MultiJobResponse>('/api/v1/scraping/jobs', {
      method: 'POST',
      body: JSON.stringify({ source: 'all' }),
    }),

  getScrapeJob: (jobId: number) =>
    fetchAPI<ScrapeJob>(`/api/v1/scraping/jobs/${jobId}`),

  getLatestScrapeStatus: (source = 'publi24') =>
    fetchAPI<LatestJobStatus>(`/api/v1/scraping/jobs/latest?source=${source}`),

  /** Status simultan pentru toate sursele. */
  getAllSourcesStatus: () =>
    fetchAPI<AllSourcesStatus>('/api/v1/scraping/status'),
};
