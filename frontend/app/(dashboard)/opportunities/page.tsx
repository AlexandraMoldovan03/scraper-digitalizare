'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { formatCurrency, scoreColor, scoreLabel } from '@/lib/utils';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { FullPageSpinner, EmptyState } from '@/components/ui/Spinner';
import type { OpportunityFeedItem } from '@/lib/types';
import {
  Zap,
  User,
  Home,
  ExternalLink,
  CheckCircle,
  Euro,
  Maximize2,
} from 'lucide-react';

// ── Score badge ───────────────────────────────────────────────────────────────

const SCORE_RING: Record<string, string> = {
  emerald: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  red: 'bg-red-50 text-red-700 ring-red-200',
};

function ScoreWidget({ score }: { score: number }) {
  const color = scoreColor(score);
  return (
    <div
      className={`flex flex-col items-center justify-center w-16 h-16 rounded-2xl ring-1 shrink-0 ${SCORE_RING[color]}`}
    >
      <span className="text-xl font-bold leading-none">
        {Math.round(score)}
      </span>
      <span className="text-xs font-medium mt-0.5">{scoreLabel(score)}</span>
    </div>
  );
}

// ── Status map ────────────────────────────────────────────────────────────────

const STATUS: Record<
  string,
  { label: string; variant: 'info' | 'success' | 'warning' | 'outline' }
> = {
  new: { label: 'Nou', variant: 'info' },
  viewed: { label: 'Văzut', variant: 'outline' },
  contacted: { label: 'Contactat', variant: 'success' },
  dismissed: { label: 'Respins', variant: 'outline' },
};

// ── Opportunity card ──────────────────────────────────────────────────────────

function OpportunityCard({ opp }: { opp: OpportunityFeedItem }) {
  const status = STATUS[opp.status] ?? { label: opp.status, variant: 'outline' as const };

  return (
    <Card className="hover:shadow-md transition-shadow duration-200">
      <div className="p-5">
        <div className="flex items-start gap-4">
          <ScoreWidget score={opp.score} />

          <div className="flex-1 min-w-0">
            {/* Header row */}
            <div className="flex items-center justify-between gap-2 mb-3">
              <div className="flex items-center gap-2">
                <Badge variant={status.variant}>{status.label}</Badge>
                {opp.status === 'new' && (
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                )}
              </div>
              <span className="text-xs text-gray-400 whitespace-nowrap">
                {new Date(opp.created_at).toLocaleDateString('ro-RO')}
              </span>
            </div>

            {/* Client + Listing panels */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Client */}
              <div className="bg-gray-50 rounded-xl p-3.5">
                <div className="flex items-center gap-1.5 mb-2">
                  <User className="w-3.5 h-3.5 text-gray-400" />
                  <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
                    Client
                  </span>
                </div>
                {opp.client ? (
                  <div className="space-y-1">
                    <p className="text-sm font-semibold text-gray-900">
                      {opp.client.full_name}
                    </p>
                    {opp.client.budget_max_eur != null && (
                      <p className="text-xs text-gray-500">
                        Buget max:{' '}
                        <span className="font-medium text-gray-700">
                          {formatCurrency(opp.client.budget_max_eur)}
                        </span>
                      </p>
                    )}
                    {(opp.client.min_rooms || opp.client.max_rooms) && (
                      <p className="text-xs text-gray-500">
                        Camere:{' '}
                        <span className="font-medium text-gray-700">
                          {opp.client.min_rooms && opp.client.max_rooms
                            ? `${opp.client.min_rooms}–${opp.client.max_rooms}`
                            : opp.client.min_rooms ?? opp.client.max_rooms}
                        </span>
                      </p>
                    )}
                    {opp.client.min_surface_m2 != null && (
                      <p className="text-xs text-gray-500">
                        Suprafață min:{' '}
                        <span className="font-medium text-gray-700">
                          {opp.client.min_surface_m2} mp
                        </span>
                      </p>
                    )}
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">Client șters</p>
                )}
              </div>

              {/* Listing */}
              <div className="bg-gray-50 rounded-xl p-3.5">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-1.5">
                    <Home className="w-3.5 h-3.5 text-gray-400" />
                    <span className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
                      Anunț
                    </span>
                  </div>
                  {opp.listing?.url && (
                    <a
                      href={opp.listing.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gray-300 hover:text-blue-500 transition-colors"
                      title="Deschide anunțul"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  )}
                </div>
                {opp.listing ? (
                  <div>
                    <p className="text-sm font-semibold text-gray-900 leading-snug">
                      {opp.listing.title ?? 'Fără titlu'}
                    </p>
                    <div className="flex flex-wrap gap-x-3 gap-y-1 mt-1.5">
                      {opp.listing.price_eur != null && (
                        <span className="flex items-center gap-1 text-xs font-semibold text-gray-700">
                          <Euro className="w-3 h-3 text-gray-400" />
                          {formatCurrency(opp.listing.price_eur)}
                        </span>
                      )}
                      {opp.listing.surface_m2 != null && (
                        <span className="flex items-center gap-1 text-xs text-gray-500">
                          <Maximize2 className="w-3 h-3 text-gray-400" />
                          {opp.listing.surface_m2} mp
                        </span>
                      )}
                      {opp.listing.rooms != null && (
                        <span className="text-xs text-gray-500">
                          {opp.listing.rooms} cam.
                        </span>
                      )}
                      {opp.listing.price_per_m2 != null && (
                        <span className="text-xs text-gray-400">
                          {Math.round(opp.listing.price_per_m2).toLocaleString(
                            'ro-RO'
                          )}{' '}
                          €/mp
                        </span>
                      )}
                    </div>
                  </div>
                ) : (
                  <p className="text-sm text-gray-400">Anunț șters</p>
                )}
              </div>
            </div>

            {/* Reason */}
            {opp.reason && (
              <div className="mt-3 flex items-start gap-2">
                <CheckCircle className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
                <p className="text-xs text-gray-600 leading-relaxed">
                  {opp.reason}
                </p>
              </div>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function OpportunitiesPage() {
  const queryClient = useQueryClient();
  const [result, setResult] = useState<{
    created: number;
    skipped: number;
  } | null>(null);

  const {
    data: feed = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['opportunities-feed'],
    queryFn: () => api.opportunitiesFeed(),
  });

  const generateMutation = useMutation({
    mutationFn: () => api.generateOpportunities(),
    onSuccess: (data) => {
      setResult({ created: data.created, skipped: data.skipped });
      queryClient.invalidateQueries({ queryKey: ['opportunities-feed'] });
    },
  });

  const newCount = feed.filter((o) => o.status === 'new').length;

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <p className="text-sm text-gray-400">
            {feed.length}{' '}
            {feed.length === 1 ? 'oportunitate' : 'oportunități'}
          </p>
          {newCount > 0 && (
            <Badge variant="info">{newCount} noi</Badge>
          )}
        </div>

        <div className="flex items-center gap-3">
          {result && (
            <p className="text-xs text-emerald-600 font-medium">
              ✓ {result.created} create, {result.skipped} sărite
            </p>
          )}
          <Button
            onClick={() => {
              setResult(null);
              generateMutation.mutate();
            }}
            loading={generateMutation.isPending}
          >
            <Zap className="w-4 h-4" />
            Generează oportunități
          </Button>
        </div>
      </div>

      {generateMutation.isError && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
          Eroare la generarea oportunităților. Verifică că există clienți și
          anunțuri.
        </div>
      )}

      {/* Feed */}
      {isLoading ? (
        <FullPageSpinner />
      ) : isError ? (
        <Card>
          <div className="p-10 text-center">
            <p className="text-sm text-red-500">
              Nu s-au putut încărca oportunitățile.
            </p>
          </div>
        </Card>
      ) : feed.length === 0 ? (
        <Card>
          <EmptyState
            title="Nicio oportunitate"
            description='Adaugă clienți și anunțuri, apoi apasă "Generează oportunități"'
            icon={Zap}
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4">
          {feed.map((opp) => (
            <OpportunityCard key={opp.opportunity_id} opp={opp} />
          ))}
        </div>
      )}
    </div>
  );
}
