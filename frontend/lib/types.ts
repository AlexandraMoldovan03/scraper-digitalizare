export interface City {
  id: number;
  name: string;
  county?: string | null;
  slug?: string | null;
  county_code?: string | null;
  locality_type?: string | null;
}

export interface Source {
  id: number;
  name: string;
  base_url?: string | null;
  slug?: string | null;
}

export interface Client {
  id: number;
  organization_id: number;
  full_name: string;
  phone?: string | null;
  email?: string | null;
  client_type: string;
  budget_min_eur?: number | null;
  budget_max_eur?: number | null;
  preferred_city_id?: number | null;
  min_rooms?: number | null;
  max_rooms?: number | null;
  min_surface_m2?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ClientCreate {
  full_name: string;
  phone?: string;
  email?: string;
  client_type?: string;
  budget_min_eur?: number;
  budget_max_eur?: number;
  preferred_city_id?: number;
  min_rooms?: number;
  max_rooms?: number;
  min_surface_m2?: number;
  notes?: string;
}

export interface MarketListing {
  id: number;
  source_id?: number | null;
  city_id?: number | null;
  url?: string | null;
  title?: string | null;
  description?: string | null;
  price_eur?: number | null;
  currency?: string | null;
  rooms?: number | null;
  surface_m2?: number | null;
  price_per_m2?: number | null;
  property_type?: string | null;
  transaction_type?: string | null;
  is_active: boolean;
  published_at?: string | null;
  first_seen_at: string;
  last_seen_at: string;
  // Zone fields
  zone_raw?: string | null;
  zone_normalized?: string | null;
  // Câmpuri din raw_payload (fără migrație)
  data_quality?: 'valid' | 'warning';
  quality_warnings?: string[];
  image_urls?: string[];
  location_raw?: string | null;
  // Câmpuri extinse
  seller_type?: 'private' | 'agency' | 'developer' | 'unknown' | null;
  latest_run_state?: 'new' | 'modified' | 'unchanged' | null;
  listing_status?: 'active' | 'possibly_inactive' | 'inactive' | null;
}

export interface OpportunityFeedItem {
  opportunity_id: number;
  score: number;
  status: string;
  listing_id: number;
  market_listing: MarketListing;
  client_id: number;
  client_name: string;
  client_budget_max_eur?: number | null;
  notes?: string | null;
}

export interface GenerateOpportunitiesResult {
  generated: number;
  skipped: number;
}

export interface Organization {
  id: number;
  name: string;
  is_active: boolean;
}

export interface ScrapeJob {
  id: number;
  source_name: string;
  trigger_type: string;
  status: string;
  queued_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  pages_processed: number;
  listings_found: number;
  listings_created: number;
  listings_updated: number;
  listings_unchanged: number;
  listings_failed: number;
  listings_inserted: number;
  warnings_count: number;
  error_message?: string | null;
}

export interface LatestJobStatus {
  job: ScrapeJob | null;
  source: string;
}

export interface SourceStatus {
  source_key: string;
  display_name: string;
  is_active: boolean;
  active_job: ScrapeJob | null;
  last_completed: ScrapeJob | null;
  cooldown_remaining_seconds: number;
}

export type AllSourcesStatus = Record<string, SourceStatus>;

export interface MultiJobResponse {
  jobs: ScrapeJob[];
  already_active: string[];
  skipped_inactive: string[];
}
