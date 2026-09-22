'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { formatCurrency, scoreColor } from '@/lib/utils';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Zap, Users, Building2, TrendingUp, ArrowUpRight, AlertCircle } from 'lucide-react';

function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  iconBg,
  iconColor,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  iconBg: string;
  iconColor: string;
}) {
  return (
    <Card>
      <CardContent>
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
              {title}
            </p>
            <p className="mt-2 text-3xl font-bold text-gray-900">{value}</p>
            {subtitle && (
              <p className="mt-1 text-sm text-gray-400">{subtitle}</p>
            )}
          </div>
          <div
            className={`w-11 h-11 rounded-xl flex items-center justify-center shrink-0 ${iconBg}`}
          >
            <Icon className={`w-5 h-5 ${iconColor}`} />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

const SCORE_STYLES: Record<string, string> = {
  emerald: 'bg-emerald-50 text-emerald-700',
  blue: 'bg-blue-50 text-blue-700',
  amber: 'bg-amber-50 text-amber-700',
  red: 'bg-red-50 text-red-700',
};

export default function DashboardPage() {
  const { data: clients = [] } = useQuery({
    queryKey: ['clients'],
    queryFn: () => api.clients(),
  });

  const { data: listings = [] } = useQuery({
    queryKey: ['listings'],
    queryFn: () => api.listings(),
  });

  const { data: feed = [] } = useQuery({
    queryKey: ['opportunities-feed'],
    queryFn: () => api.opportunitiesFeed(),
  });

  const newOpportunities = feed.filter((o) => o.status === 'new').length;
  const activeListings = listings.filter((l) => l.is_active).length;
  const avgScore =
    feed.length > 0
      ? Math.round(feed.reduce((acc, o) => acc + o.score, 0) / feed.length)
      : null;

  const recent = feed.slice(0, 6);

  return (
    <div className="space-y-6">
      {/* Stats grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <StatCard
          title="Oportunități noi"
          value={newOpportunities}
          subtitle={`din ${feed.length} totale`}
          icon={Zap}
          iconBg="bg-blue-50"
          iconColor="text-blue-600"
        />
        <StatCard
          title="Clienți activi"
          value={clients.length}
          subtitle="în baza de date"
          icon={Users}
          iconBg="bg-emerald-50"
          iconColor="text-emerald-600"
        />
        <StatCard
          title="Anunțuri monitorizate"
          value={activeListings}
          subtitle="anunțuri active"
          icon={Building2}
          iconBg="bg-amber-50"
          iconColor="text-amber-600"
        />
        <StatCard
          title="Scor mediu"
          value={avgScore !== null ? `${avgScore}%` : '—'}
          subtitle="al oportunităților"
          icon={TrendingUp}
          iconBg="bg-violet-50"
          iconColor="text-violet-600"
        />
      </div>

      {/* Recent opportunities */}
      <Card>
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-900">
            Oportunități recente
          </h2>
          <Link
            href="/opportunities"
            className="text-xs text-blue-600 hover:text-blue-700 font-medium flex items-center gap-1"
          >
            Vezi toate
            <ArrowUpRight className="w-3 h-3" />
          </Link>
        </div>

        {recent.length === 0 ? (
          <div className="py-14 flex flex-col items-center gap-2 text-center">
            <AlertCircle className="w-8 h-8 text-gray-200" />
            <p className="text-sm text-gray-500">Nicio oportunitate generată</p>
            <Link
              href="/opportunities"
              className="text-xs text-blue-600 hover:underline"
            >
              Generează acum →
            </Link>
          </div>
        ) : (
          <div className="divide-y divide-gray-50">
            {recent.map((opp) => {
              const sc = scoreColor(opp.score);
              return (
                <div
                  key={opp.opportunity_id}
                  className="px-5 py-3.5 flex items-center gap-4 hover:bg-gray-50/60 transition-colors"
                >
                  {/* Score bubble */}
                  <div
                    className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 text-sm font-bold ${SCORE_STYLES[sc]}`}
                  >
                    {Math.round(opp.score)}
                  </div>

                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">
                      {opp.client?.full_name ?? 'Client necunoscut'}
                    </p>
                    <p className="text-xs text-gray-400 truncate mt-0.5">
                      {opp.listing?.title ?? 'Anunț indisponibil'}
                    </p>
                  </div>

                  <div className="shrink-0 text-right space-y-0.5">
                    {opp.listing?.price_eur != null && (
                      <p className="text-sm font-semibold text-gray-900">
                        {formatCurrency(opp.listing.price_eur)}
                      </p>
                    )}
                    <Badge variant={opp.status === 'new' ? 'info' : 'outline'}>
                      {opp.status === 'new' ? 'Nou' : opp.status}
                    </Badge>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
