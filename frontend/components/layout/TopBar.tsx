'use client';

import { useState, useEffect } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { Bell, LogOut } from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { clearAuth, getUser } from '@/lib/auth';
import type { AuthUser } from '@/lib/auth';

const PAGE_META: Record<string, { title: string; subtitle: string }> = {
  '/': { title: 'Dashboard', subtitle: 'Bine ai venit în AgencyIntel' },
  '/clients': { title: 'Clienți', subtitle: 'Gestionează clienții agenției' },
  '/listings': { title: 'Anunțuri piață', subtitle: 'Toate anunțurile din județul Alba' },
  '/opportunities': { title: 'Oportunități', subtitle: 'Match-uri detectate automat' },
  '/settings': { title: 'Setări', subtitle: 'Configurare platformă' },
};

export function TopBar() {
  const pathname = usePathname();
  const router = useRouter();

  // getUser() citește din localStorage — nu e disponibil la SSR.
  // Inițializăm cu null (același pe server și client) și populăm după hydration.
  const [user, setUser] = useState<AuthUser | null>(null);
  useEffect(() => {
    setUser(getUser());
  }, []);

  const meta = PAGE_META[pathname] ?? { title: 'AgencyIntel', subtitle: '' };

  const initials = user?.full_name
    ? user.full_name.split(' ').map((w) => w[0]).join('').toUpperCase().slice(0, 2)
    : user?.email?.slice(0, 2).toUpperCase() ?? 'AI';

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(),
    onSettled: () => {
      clearAuth();
      router.push('/login');
      router.refresh();
    },
  });

  return (
    <header className="h-16 bg-white border-b border-gray-100 flex items-center justify-between px-6 shrink-0">
      <div>
        <h1 className="text-base font-semibold text-gray-900">{meta.title}</h1>
        {meta.subtitle && (
          <p className="text-xs text-gray-400 mt-0.5">{meta.subtitle}</p>
        )}
      </div>

      <div className="flex items-center gap-1">
        <button className="relative p-2 text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg transition-colors">
          <Bell className="w-4 h-4" />
          <span className="absolute top-2 right-2 w-1.5 h-1.5 bg-blue-500 rounded-full" />
        </button>

        <div className="ml-2 pl-3 border-l border-gray-200 flex items-center gap-2.5">
          <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center shrink-0">
            <span className="text-blue-700 text-xs font-semibold">{initials}</span>
          </div>

          <div className="hidden sm:block">
            <p className="text-sm font-medium text-gray-700 leading-none">
              {user?.full_name ?? user?.email ?? 'Utilizator'}
            </p>
            {user?.email && user.full_name && (
              <p className="text-xs text-gray-400 mt-0.5">{user.email}</p>
            )}
          </div>

          <button
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
            title="Delogare"
            className="ml-1 p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-colors"
          >
            <LogOut className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
}
