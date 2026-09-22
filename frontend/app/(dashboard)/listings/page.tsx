'use client';

import { useState, useMemo, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { formatCurrency } from '@/lib/utils';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { FullPageSpinner, EmptyState } from '@/components/ui/Spinner';
import type { MarketListing, ScrapeJob, AllSourcesStatus, SourceStatus } from '@/lib/types';
import {
  Building2,
  ExternalLink,
  SlidersHorizontal,
  X,
  AlertTriangle,
  CheckCircle2,
  ImageOff,
  RefreshCw,
  MapPin,
  Calendar,
  TrendingUp,
  ChevronUp,
  ChevronDown,
  ChevronsUpDown,
  Play,
  Clock,
  Loader2,
  CheckCheck,
  XCircle,
  BarChart3,
} from 'lucide-react';

// ── Scraping Panel — multi-sursă ─────────────────────────────────────────────

function formatRelativeTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const diff = Date.now() - new Date(dateStr).getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'acum câteva secunde';
  if (minutes < 60) return `acum ${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `acum ${hours}h`;
  return new Date(dateStr).toLocaleDateString('ro-RO');
}

function formatCooldown(seconds: number): string {
  if (seconds <= 0) return '';
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

const STATUS_CONFIG: Record<string, { label: string; color: string; icon: React.ElementType }> = {
  queued:    { label: 'În așteptare', color: 'text-blue-600 bg-blue-50 border-blue-200', icon: Clock },
  running:   { label: 'În rulare',    color: 'text-amber-600 bg-amber-50 border-amber-200', icon: Loader2 },
  completed: { label: 'Finalizat',    color: 'text-emerald-600 bg-emerald-50 border-emerald-200', icon: CheckCheck },
  success:   { label: 'Finalizat',    color: 'text-emerald-600 bg-emerald-50 border-emerald-200', icon: CheckCheck },
  failed:    { label: 'Eșuat',        color: 'text-red-600 bg-red-50 border-red-200', icon: XCircle },
};

const TERMINAL_STATUSES = ['completed', 'failed', 'success'];
const ACTIVE_JOB_STATUSES = ['queued', 'running'];

// ── SourceCard — o sursă individuală ─────────────────────────────────────────

function SourceCard({
  sourceKey,
  status,
  onJobCompleted,
}: {
  sourceKey: string;
  status: SourceStatus | undefined;
  onJobCompleted: () => void;
}) {
  const [showReport, setShowReport] = useState(false);
  const [trackedJobId, setTrackedJobId] = useState<number | null>(null);

  // Polling job activ pentru această sursă
  const { data: polledJob } = useQuery<ScrapeJob>({
    queryKey: ['scraping-job', trackedJobId],
    queryFn: () => api.getScrapeJob(trackedJobId!),
    enabled: !!trackedJobId,
    refetchInterval: (query) => {
      const job = query.state.data as ScrapeJob | undefined;
      if (!job || TERMINAL_STATUSES.includes(job.status)) return false;
      return 2500;
    },
  });

  // Detectăm job activ din status global
  const activeJobFromStatus = status?.active_job ?? null;
  useEffect(() => {
    if (activeJobFromStatus && !trackedJobId) {
      setTrackedJobId(activeJobFromStatus.id);
      setShowReport(false);
    }
  }, [activeJobFromStatus?.id]);

  // Când job-ul devine terminal
  useEffect(() => {
    if (!polledJob) return;
    if (TERMINAL_STATUSES.includes(polledJob.status)) {
      setShowReport(true);
      setTrackedJobId(null);
      if (polledJob.status !== 'failed') onJobCompleted();
    }
  }, [polledJob?.status]);

  const triggerMutation = useMutation({
    mutationFn: () => api.triggerScrape(sourceKey),
    onSuccess: (job) => {
      setTrackedJobId(job.id);
      setShowReport(false);
    },
    // Ignorăm eroarea 400 pentru surse inactive (gestionată prin disabled)
    onError: () => {},
  });

  if (!status) return null;

  const { is_active, display_name, cooldown_remaining_seconds } = status;
  const activeJob = activeJobFromStatus ?? (trackedJobId ? polledJob : null);
  const displayJob = polledJob ?? activeJob ?? status.last_completed;
  const isRunning = !!activeJob || ACTIVE_JOB_STATUSES.includes(polledJob?.status ?? '');
  const isDisabled = !is_active || isRunning || triggerMutation.isPending || cooldown_remaining_seconds > 0;
  const statusCfg = displayJob ? STATUS_CONFIG[displayJob.status] ?? STATUS_CONFIG.queued : null;

  return (
    <div className="flex flex-col gap-2 min-w-0">
      {/* Titlu sursă + badge status */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-700">{display_name}</span>

          {!is_active ? (
            <span className="inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-gray-100 text-gray-400 border border-gray-200">
              Neconfigurat
            </span>
          ) : statusCfg && displayJob ? (
            <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${statusCfg.color}`}>
              <statusCfg.icon className={`w-2.5 h-2.5 ${displayJob.status === 'running' ? 'animate-spin' : ''}`} />
              {statusCfg.label}
            </span>
          ) : (
            <span className="text-[10px] text-gray-400">Nicio rulare recentă</span>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          {is_active && status.last_completed?.finished_at && (
            <span className="text-[10px] text-gray-400 hidden sm:block">
              {formatRelativeTime(status.last_completed.finished_at)}
            </span>
          )}
          {is_active && cooldown_remaining_seconds > 0 && !isRunning && (
            <span className="text-[10px] text-gray-400">{formatCooldown(cooldown_remaining_seconds)}</span>
          )}
          <Button
            size="sm"
            variant={isRunning ? 'outline' : 'primary'}
            onClick={() => triggerMutation.mutate()}
            loading={triggerMutation.isPending}
            disabled={isDisabled}
          >
            {isRunning ? (
              <><Loader2 className="w-3 h-3 animate-spin" /> Rulează...</>
            ) : (
              <><Play className="w-3 h-3" /> Actualizează</>
            )}
          </Button>
        </div>
      </div>

      {/* Progres */}
      {isRunning && displayJob && displayJob.listings_found > 0 && (
        <div className="text-[10px] text-gray-400 flex gap-2 pl-1">
          <span>{displayJob.listings_found} găsite</span>
          {displayJob.listings_created > 0 && <span className="text-emerald-600">+{displayJob.listings_created} noi</span>}
          {displayJob.listings_updated > 0 && <span className="text-blue-600">~{displayJob.listings_updated} actualizate</span>}
        </div>
      )}

      {/* Raport final */}
      {showReport && displayJob && TERMINAL_STATUSES.includes(displayJob.status) && (
        <div className={`rounded-lg border px-3 py-2 text-xs ${
          displayJob.status === 'failed' ? 'bg-red-50 border-red-200' : 'bg-emerald-50 border-emerald-200'
        }`}>
          {displayJob.status === 'failed' ? (
            <div className="flex items-start gap-1.5">
              <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0 mt-0.5" />
              <div>
                <span className="font-medium text-red-700">Import eșuat</span>
                {displayJob.error_message && (
                  <p className="text-red-600 mt-0.5">{displayJob.error_message}</p>
                )}
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 flex-wrap">
              <BarChart3 className="w-3.5 h-3.5 text-emerald-600 shrink-0" />
              <span><span className="font-semibold text-emerald-700">+{displayJob.listings_created}</span> noi</span>
              <span><span className="font-semibold text-blue-700">~{displayJob.listings_updated}</span> actualizate</span>
              <span><span className="font-semibold text-gray-500">{displayJob.listings_unchanged}</span> neschimbate</span>
              {displayJob.listings_failed > 0 && (
                <span><span className="font-semibold text-red-600">{displayJob.listings_failed}</span> eșuate</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── ScrapingPanel — container multi-sursă ─────────────────────────────────────

function ScrapingPanel({ onJobCompleted }: { onJobCompleted: () => void }) {
  // Polling toate sursele simultan
  const { data: allStatus, refetch: refetchAll } = useQuery<AllSourcesStatus>({
    queryKey: ['scraping-status'],
    queryFn: () => api.getAllSourcesStatus(),
    refetchInterval: (query) => {
      const data = query.state.data as AllSourcesStatus | undefined;
      if (!data) return 5_000;
      const hasActive = Object.values(data).some(
        (s) => s.active_job && ACTIVE_JOB_STATUSES.includes(s.active_job.status)
      );
      return hasActive ? 3_000 : 10_000;
    },
    staleTime: 2_000,
  });

  const triggerAllMutation = useMutation({
    mutationFn: () => api.triggerScrapeAll(),
    onSettled: () => refetchAll(),
  });

  const sourceKeys = allStatus ? Object.keys(allStatus) : ['publi24', 'imobiliare_ro'];
  const anyActive = allStatus
    ? Object.values(allStatus).some((s) => s.active_job && ACTIVE_JOB_STATUSES.includes(s.active_job.status))
    : false;
  const allInactive = allStatus
    ? Object.values(allStatus).every((s) => !s.is_active)
    : false;

  return (
    <div className="bg-white rounded-xl border border-gray-100 px-5 py-4">
      {/* Header: titlu + buton "Actualizează toate" */}
      <div className="flex items-center justify-between mb-4">
        <span className="text-sm font-semibold text-gray-700">Surse de date</span>
        <Button
          size="sm"
          variant="outline"
          onClick={() => triggerAllMutation.mutate()}
          loading={triggerAllMutation.isPending}
          disabled={anyActive || allInactive || triggerAllMutation.isPending}
        >
          <Play className="w-3 h-3" />
          Actualizează toate
        </Button>
      </div>

      {/* O linie per sursă */}
      <div className="flex flex-col divide-y divide-gray-50">
        {sourceKeys.map((key, i) => (
          <div key={key} className={i > 0 ? 'pt-3 mt-3' : ''}>
            <SourceCard
              sourceKey={key}
              status={allStatus?.[key]}
              onJobCompleted={() => { refetchAll(); onJobCompleted(); }}
            />
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function daysOnMarket(firstSeenAt: string): number {
  const diff = Date.now() - new Date(firstSeenAt).getTime();
  return Math.floor(diff / (1000 * 60 * 60 * 24));
}

function formatPublishedAt(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('ro-RO', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  });
}

type SortKey = 'price_eur' | 'surface_m2' | 'price_per_m2' | 'days' | 'published_at' | null;
type SortDir = 'asc' | 'desc';

// ── Thumbnail ─────────────────────────────────────────────────────────────────

function ListingThumbnail({ listing }: { listing: MarketListing }) {
  const [failed, setFailed] = useState(false);
  const firstImage =
    !failed && listing.image_urls && listing.image_urls.length > 0
      ? listing.image_urls[0]
      : null;

  if (!firstImage) {
    return (
      <div className="w-14 h-14 rounded-lg bg-gray-100 flex items-center justify-center shrink-0">
        <Building2 className="w-5 h-5 text-gray-300" />
      </div>
    );
  }

  return (
    <a href={listing.url ?? '#'} target="_blank" rel="noopener noreferrer" className="shrink-0">
      <img
        src={firstImage}
        alt={listing.title ?? ''}
        referrerPolicy="no-referrer"
        loading="lazy"
        onError={() => setFailed(true)}
        className="w-14 h-14 object-cover rounded-lg border border-gray-100"
      />
    </a>
  );
}

// ── Quality cell ──────────────────────────────────────────────────────────────

function QualityCell({ quality, warnings }: { quality?: string; warnings?: string[] }) {
  const [open, setOpen] = useState(false);
  if (quality !== 'warning') {
    return (
      <div className="flex items-center gap-1 text-emerald-600">
        <CheckCircle2 className="w-3.5 h-3.5" />
        <span className="text-xs font-medium">Valid</span>
      </div>
    );
  }
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 text-amber-600 hover:text-amber-700 transition-colors"
      >
        <AlertTriangle className="w-3.5 h-3.5" />
        <span className="text-xs font-medium underline decoration-dotted">Warning</span>
      </button>
      {open && warnings && warnings.length > 0 && (
        <div className="absolute z-20 top-6 left-0 bg-white border border-amber-200 rounded-lg shadow-lg p-3 w-72">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-semibold text-amber-700">Probleme detectate</span>
            <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600">
              <X className="w-3 h-3" />
            </button>
          </div>
          <ul className="space-y-1">
            {warnings.map((w, i) => (
              <li key={i} className="text-xs text-gray-700 flex items-start gap-1.5">
                <span className="text-amber-500 shrink-0 mt-0.5">•</span>
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// ── Sort header ───────────────────────────────────────────────────────────────

function SortHeader({
  label,
  sortKey,
  current,
  dir,
  onSort,
}: {
  label: string;
  sortKey: SortKey;
  current: SortKey;
  dir: SortDir;
  onSort: (k: SortKey) => void;
}) {
  const active = current === sortKey;
  return (
    <th
      className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap cursor-pointer select-none hover:text-gray-600 transition-colors"
      onClick={() => onSort(sortKey)}
    >
      <span className="flex items-center gap-1">
        {label}
        {active ? (
          dir === 'asc' ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />
        ) : (
          <ChevronsUpDown className="w-3 h-3 opacity-40" />
        )}
      </span>
    </th>
  );
}

// ── Constants ─────────────────────────────────────────────────────────────────

const ROOMS_OPTIONS = [
  { value: '', label: 'Toate camerele' },
  { value: '1', label: '1 cameră' },
  { value: '2', label: '2 camere' },
  { value: '3', label: '3 camere' },
  { value: '4', label: '4+ camere' },
];

const QUALITY_OPTIONS = [
  { value: '', label: 'Toate' },
  { value: 'valid', label: 'Valid' },
  { value: 'warning', label: 'Warning' },
];

const SOURCE_OPTIONS = [
  { value: '', label: 'Toate sursele' },
  { value: 'publi24', label: 'Publi24' },
  { value: 'imobiliare_ro', label: 'Imobiliare.ro' },
];

// ── Seller Type Badge ─────────────────────────────────────────────────────────

function SellerTypeBadge({ sellerType }: { sellerType?: string | null }) {
  const config: Record<string, { label: string; color: string }> = {
    private:   { label: 'Persoană fizică', color: 'text-purple-700 bg-purple-50 border-purple-200' },
    agency:    { label: 'Agenție',         color: 'text-blue-700 bg-blue-50 border-blue-200' },
    developer: { label: 'Developer',       color: 'text-orange-700 bg-orange-50 border-orange-200' },
    unknown:   { label: '—',              color: 'text-gray-400 bg-gray-50 border-gray-200' },
  };
  if (!sellerType || sellerType === 'unknown') {
    return <span className="text-gray-300 text-xs">—</span>;
  }
  const cfg = config[sellerType];
  if (!cfg) return <span className="text-xs text-gray-400">{sellerType}</span>;
  return (
    <span className={`inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded-full border ${cfg.color}`}>
      {cfg.label}
    </span>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ListingsPage() {
  const queryClient = useQueryClient();

  // Filtre
  const [filterCity, setFilterCity] = useState('');
  const [selectedCityId, setSelectedCityId] = useState<number | null>(null);
  const [filterZone, setFilterZone] = useState('');
  const [filterRooms, setFilterRooms] = useState('');
  const [filterMaxPrice, setFilterMaxPrice] = useState('');
  const [filterMaxPpm2, setFilterMaxPpm2] = useState('');
  const [filterQuality, setFilterQuality] = useState('');
  const [filterLocality, setFilterLocality] = useState('');
  const [filterSource, setFilterSource] = useState('');

  // Sortare
  const [sortKey, setSortKey] = useState<SortKey>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const [refreshMsg, setRefreshMsg] = useState('');

  const { data: listings = [], isLoading, isError, isFetching } = useQuery({
    queryKey: ['listings', selectedCityId, filterZone, filterRooms, filterMaxPrice, filterMaxPpm2, filterQuality],
    queryFn: () => api.listings({
      city_id: selectedCityId ?? undefined,
      zone: filterZone || undefined,
      rooms: filterRooms ? Number(filterRooms) : undefined,
      max_price: filterMaxPrice ? Number(filterMaxPrice) : undefined,
      max_price_per_m2: filterMaxPpm2 ? Number(filterMaxPpm2) : undefined,
      data_quality: filterQuality || undefined,
    }),
  });

  const { data: cities = [] } = useQuery({
    queryKey: ['cities'],
    queryFn: () => api.cities(),
  });

  const { data: sources = [] } = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.sources(),
  });

  const { data: zones = [] } = useQuery({
    queryKey: ['zones', selectedCityId],
    queryFn: () => api.zones(selectedCityId!),
    enabled: !!selectedCityId,
  });

  const refreshMutation = useMutation({
    mutationFn: () => api.refreshImages(30),
    onSuccess: (data) => {
      setRefreshMsg(`✓ ${data.updated} actualizate, ${data.skipped} sărite`);
      queryClient.invalidateQueries({ queryKey: ['listings'] });
    },
  });

  const cityMap = Object.fromEntries(cities.map((c) => [c.id, c.name]));
  const sourceMap = Object.fromEntries(sources.map((s) => [s.id, s.name]));

  const cityOptions = [
    { value: '', label: 'Toate orașele' },
    ...cities.map((c) => ({ value: String(c.id), label: c.name })),
  ];

  const zoneOptions = [
    { value: '', label: selectedCityId ? 'Toate zonele' : 'Selectați mai întâi un oraș' },
    ...zones.map((z) => ({ value: z, label: z })),
  ];

  // Localități unice din location_raw (from current results)
  const localities = useMemo(() => {
    const set = new Set<string>();
    listings.forEach((l) => { if (l.location_raw) set.add(l.location_raw); });
    return Array.from(set).sort();
  }, [listings]);

  const localityOptions = [
    { value: '', label: 'Toate localitățile' },
    ...localities.map((loc) => ({ value: loc, label: loc })),
  ];

  // Stats
  const withoutImages = listings.filter((l) => !l.image_urls?.length).length;
  const warningCount = listings.filter((l) => l.data_quality === 'warning').length;
  const newCount = listings.filter((l) => daysOnMarket(l.first_seen_at) <= 7).length;

  const avgPrice = useMemo(() => {
    const valid = listings.filter((l) => l.price_eur);
    if (!valid.length) return null;
    return Math.round(valid.reduce((s, l) => s + l.price_eur!, 0) / valid.length);
  }, [listings]);

  const avgPpm2 = useMemo(() => {
    const valid = listings.filter((l) => l.price_per_m2);
    if (!valid.length) return null;
    return Math.round(valid.reduce((s, l) => s + l.price_per_m2!, 0) / valid.length);
  }, [listings]);

  const hasFilters = filterCity || filterZone || filterRooms || filterMaxPrice || filterMaxPpm2 || filterQuality || filterLocality || filterSource;

  // Client-side locality filter (zone/city/rooms/price/quality are server-side)
  const filtered = useMemo(() => {
    let result = listings.filter((l) => {
      if (filterLocality && l.location_raw !== filterLocality) return false;
      if (filterSource) {
        const srcName = sourceMap[l.source_id ?? 0] ?? '';
        if (!srcName.toLowerCase().includes(filterSource === 'imobiliare_ro' ? 'imobiliare' : filterSource)) return false;
      }
      return true;
    });

    // Sortare
    if (sortKey) {
      result = [...result].sort((a, b) => {
        let av: number, bv: number;
        if (sortKey === 'days') {
          av = daysOnMarket(a.first_seen_at);
          bv = daysOnMarket(b.first_seen_at);
        } else if (sortKey === 'published_at') {
          av = a.published_at ? new Date(a.published_at).getTime() : 0;
          bv = b.published_at ? new Date(b.published_at).getTime() : 0;
        } else {
          av = (a[sortKey] as number) ?? 0;
          bv = (b[sortKey] as number) ?? 0;
        }
        return sortDir === 'asc' ? av - bv : bv - av;
      });
    }

    return result;
  }, [listings, filterLocality, filterSource, sourceMap, sortKey, sortDir]);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function handleCityChange(value: string) {
    setFilterCity(value);
    const cityId = value ? Number(value) : null;
    setSelectedCityId(cityId);
    setFilterZone(''); // reset zone when city changes
  }

  function resetFilters() {
    setFilterCity('');
    setSelectedCityId(null);
    setFilterZone('');
    setFilterLocality('');
    setFilterRooms('');
    setFilterMaxPrice('');
    setFilterMaxPpm2('');
    setFilterQuality('');
    setFilterSource('');
  }

  function handleJobCompleted() {
    // Reload listings, cities, zones și statistici după import reușit
    queryClient.invalidateQueries({ queryKey: ['listings'] });
    queryClient.invalidateQueries({ queryKey: ['cities'] });
    queryClient.invalidateQueries({ queryKey: ['zones'] });
    queryClient.invalidateQueries({ queryKey: ['sources'] });
  }

  return (
    <div className="space-y-5">

      {/* Scraping Panel */}
      <ScrapingPanel onJobCompleted={handleJobCompleted} />

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total anunțuri', value: listings.length, icon: Building2, color: 'text-blue-600 bg-blue-50' },
          { label: 'Noi (≤7 zile)', value: newCount, icon: Calendar, color: 'text-emerald-600 bg-emerald-50' },
          { label: 'Preț mediu', value: avgPrice ? `${avgPrice.toLocaleString('ro-RO')} €` : '—', icon: TrendingUp, color: 'text-purple-600 bg-purple-50' },
          { label: 'Medie €/mp', value: avgPpm2 ? `${avgPpm2.toLocaleString('ro-RO')} €` : '—', icon: TrendingUp, color: 'text-orange-600 bg-orange-50' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="bg-white rounded-xl border border-gray-100 px-4 py-3 flex items-center gap-3">
            <div className={`w-9 h-9 rounded-lg flex items-center justify-center ${color}`}>
              <Icon className="w-4 h-4" />
            </div>
            <div>
              <p className="text-xs text-gray-400">{label}</p>
              <p className="text-base font-semibold text-gray-900">{value}</p>
            </div>
          </div>
        ))}
      </div>

      {/* Banners */}
      {withoutImages > 0 && (
        <div className="flex items-center justify-between gap-4 bg-blue-50 border border-blue-200 rounded-xl px-4 py-3">
          <div className="flex items-center gap-2.5">
            <ImageOff className="w-4 h-4 text-blue-500 shrink-0" />
            <p className="text-sm text-blue-800">
              <span className="font-semibold">{withoutImages}</span>{' '}
              {withoutImages === 1 ? 'anunț fără imagini' : 'anunțuri fără imagini'}.
              {refreshMsg && <span className="ml-2 text-emerald-700 font-medium">{refreshMsg}</span>}
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={() => { setRefreshMsg(''); refreshMutation.mutate(); }}
            loading={refreshMutation.isPending}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            Adaugă imagini lipsă
          </Button>
        </div>
      )}

      {warningCount > 0 && (
        <div className="flex items-center gap-3 bg-amber-50 border border-amber-200 rounded-xl px-4 py-3">
          <AlertTriangle className="w-4 h-4 text-amber-600 shrink-0" />
          <p className="text-sm text-amber-800">
            <span className="font-semibold">{warningCount}</span>{' '}
            {warningCount === 1 ? 'anunț' : 'anunțuri'} cu inconsistențe.{' '}
            <button onClick={() => setFilterQuality('warning')} className="underline hover:no-underline">
              Filtrează
            </button>
          </p>
        </div>
      )}

      {/* Filters */}
      <Card>
        <div className="px-5 py-4">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <SlidersHorizontal className="w-4 h-4 text-gray-400" />
              <span className="text-sm font-semibold text-gray-700">Filtre</span>
            </div>
            {hasFilters && (
              <button
                onClick={resetFilters}
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 transition-colors"
              >
                <X className="w-3 h-3" />
                Resetează
              </button>
            )}
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-7 gap-3">
            <Select label="Localitate" value={filterLocality} options={localityOptions} onChange={(e) => setFilterLocality(e.target.value)} />
            <Select label="Oraș (DB)" value={filterCity} options={cityOptions} onChange={(e) => handleCityChange(e.target.value)} />
            <Select
              label="Zonă"
              value={filterZone}
              options={zoneOptions}
              onChange={(e) => setFilterZone(e.target.value)}
              disabled={!selectedCityId}
            />
            <Select label="Camere" value={filterRooms} options={ROOMS_OPTIONS} onChange={(e) => setFilterRooms(e.target.value)} />
            <Input label="Preț maxim (EUR)" type="number" placeholder="ex: 100 000" value={filterMaxPrice} onChange={(e) => setFilterMaxPrice(e.target.value)} />
            <Input label="EUR/mp maxim" type="number" placeholder="ex: 2 000" value={filterMaxPpm2} onChange={(e) => setFilterMaxPpm2(e.target.value)} />
            <Select label="Calitate" value={filterQuality} options={QUALITY_OPTIONS} onChange={(e) => setFilterQuality(e.target.value)} />
            <Select label="Sursă" value={filterSource} options={SOURCE_OPTIONS} onChange={(e) => setFilterSource(e.target.value)} />
          </div>
        </div>
      </Card>

      {/* Count */}
      <p className="text-sm text-gray-400">
        {filtered.length} {filtered.length === 1 ? 'anunț' : 'anunțuri'}
        {hasFilters && ` (din ${listings.length})`}
      </p>

      {/* Error banner — background refetch eșuat, dar datele vechi sunt vizibile */}
      {isError && listings.length > 0 && (
        <div className="flex items-center gap-3 bg-red-50 border border-red-200 rounded-xl px-4 py-3">
          <AlertTriangle className="w-4 h-4 text-red-500 shrink-0" />
          <p className="text-sm text-red-700">Nu s-a putut actualiza lista. Datele afișate pot fi incomplete.</p>
        </div>
      )}

      {/* Table */}
      <Card>
        {isLoading ? (
          <FullPageSpinner />
        ) : isError && listings.length === 0 ? (
          <div className="p-10 text-center space-y-1">
            <p className="text-sm text-red-500">Nu s-au putut încărca anunțurile.</p>
            <p className="text-xs text-gray-400">Verifică că backend-ul rulează la http://127.0.0.1:8000</p>
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            title="Niciun anunț"
            description={hasFilters ? 'Niciun anunț nu corespunde filtrelor' : 'Niciun anunț în baza de date'}
            icon={Building2}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap">Anunț</th>
                  <SortHeader label="Preț" sortKey="price_eur" current={sortKey} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Suprafață" sortKey="surface_m2" current={sortKey} dir={sortDir} onSort={handleSort} />
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap">Cam.</th>
                  <SortHeader label="€/mp" sortKey="price_per_m2" current={sortKey} dir={sortDir} onSort={handleSort} />
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap">
                    <span className="flex items-center gap-1"><MapPin className="w-3 h-3" />Localitate</span>
                  </th>
                  <SortHeader label="Publicat" sortKey="published_at" current={sortKey} dir={sortDir} onSort={handleSort} />
                  <SortHeader label="Zile piață" sortKey="days" current={sortKey} dir={sortDir} onSort={handleSort} />
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap">Sursă</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap">Vânzător</th>
                  <th className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest whitespace-nowrap">Calitate</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((listing) => {
                  const isWarning = listing.data_quality === 'warning';
                  const days = daysOnMarket(listing.first_seen_at);
                  const isNew = listing.latest_run_state === 'new' || days <= 7;
                  const isModified = listing.latest_run_state === 'modified';
                  const unknownLocality = listing.location_raw && !listing.city_id;

                  return (
                    <tr
                      key={listing.id}
                      className={`transition-colors group hover:bg-gray-50/60 ${isWarning ? 'border-l-2 border-amber-400' : ''}`}
                    >
                      {/* Anunț = thumbnail + titlu */}
                      <td className="px-5 py-3 max-w-xs">
                        <div className="flex items-center gap-3 min-w-0">
                          <ListingThumbnail listing={listing} />
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start gap-1">
                              <p className="text-sm font-medium text-gray-900 truncate leading-snug">
                                {listing.title ?? '—'}
                              </p>
                              {listing.url && (
                                <a
                                  href={listing.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="shrink-0 text-gray-300 group-hover:text-blue-500 transition-colors mt-0.5"
                                >
                                  <ExternalLink className="w-3 h-3" />
                                </a>
                              )}
                            </div>
                            <div className="flex items-center gap-1.5 mt-0.5">
                              {isNew && (
                                <span className="inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700">
                                  NOU
                                </span>
                              )}
                              {isModified && (
                                <span className="inline-flex items-center text-[10px] font-semibold px-1.5 py-0.5 rounded-full bg-blue-100 text-blue-700">
                                  MODIFICAT
                                </span>
                              )}
                              {listing.image_urls && listing.image_urls.length > 1 && (
                                <span className="text-xs text-gray-300">+{listing.image_urls.length - 1} poze</span>
                              )}
                            </div>
                          </div>
                        </div>
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <span className="text-sm font-semibold text-gray-900">
                          {formatCurrency(listing.price_eur)}
                        </span>
                      </td>

                      <td className="px-5 py-3 text-sm text-gray-600 whitespace-nowrap">
                        {listing.surface_m2 != null ? `${listing.surface_m2} mp` : '—'}
                      </td>

                      <td className="px-5 py-3">
                        {listing.rooms != null ? (
                          <span className="text-sm text-gray-700">{listing.rooms}</span>
                        ) : (
                          <span className="text-xs text-amber-600 font-medium">?</span>
                        )}
                      </td>

                      <td className="px-5 py-3 text-sm text-gray-600 whitespace-nowrap">
                        {listing.price_per_m2 != null
                          ? `${Math.round(listing.price_per_m2).toLocaleString('ro-RO')} €`
                          : '—'}
                      </td>

                      {/* Localitate */}
                      <td className="px-5 py-3 whitespace-nowrap">
                        {listing.location_raw ? (
                          <div>
                            <div className={`flex items-center gap-1 text-sm ${unknownLocality ? 'text-amber-600' : 'text-gray-600'}`}>
                              <MapPin className="w-3 h-3 text-gray-400 shrink-0" />
                              {unknownLocality ? (
                                <span className="italic text-amber-600">Localitate necunoscută</span>
                              ) : (
                                listing.location_raw
                              )}
                            </div>
                            {listing.zone_normalized && (
                              <div className="text-xs text-gray-400 ml-4 mt-0.5">
                                zona {listing.zone_normalized}
                              </div>
                            )}
                          </div>
                        ) : listing.city_id ? (
                          <span className="text-sm text-gray-500">{cityMap[listing.city_id] ?? '—'}</span>
                        ) : (
                          <span className="text-gray-300">—</span>
                        )}
                      </td>

                      {/* Data publicării */}
                      <td className="px-5 py-3 text-xs text-gray-500 whitespace-nowrap">
                        {formatPublishedAt(listing.published_at)}
                      </td>

                      {/* Zile pe piață */}
                      <td className="px-5 py-3 whitespace-nowrap">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          days <= 7
                            ? 'bg-emerald-100 text-emerald-700'
                            : days <= 30
                            ? 'bg-blue-100 text-blue-700'
                            : 'bg-gray-100 text-gray-500'
                        }`}>
                          {days === 0 ? 'azi' : `${days}z`}
                        </span>
                      </td>

                      <td className="px-5 py-3 text-xs text-gray-400 whitespace-nowrap">
                        {listing.source_id ? sourceMap[listing.source_id] ?? `#${listing.source_id}` : '—'}
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <SellerTypeBadge sellerType={listing.seller_type} />
                      </td>

                      <td className="px-5 py-3">
                        <QualityCell quality={listing.data_quality} warnings={listing.quality_warnings} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
