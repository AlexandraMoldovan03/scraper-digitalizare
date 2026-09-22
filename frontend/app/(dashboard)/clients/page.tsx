'use client';

import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { formatCurrency, formatDate } from '@/lib/utils';
import { Card } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Modal } from '@/components/ui/Modal';
import { Input } from '@/components/ui/Input';
import { Select } from '@/components/ui/Select';
import { FullPageSpinner, EmptyState } from '@/components/ui/Spinner';
import type { ClientCreate } from '@/lib/types';
import { UserPlus, Users, Phone, Mail, MapPin, Home } from 'lucide-react';

// ── Constants ─────────────────────────────────────────────────────────────────

const CLIENT_TYPES = [
  { value: 'buyer', label: 'Cumpărător' },
  { value: 'renter', label: 'Chiriaș' },
  { value: 'investor', label: 'Investitor' },
];

const TYPE_LABEL: Record<string, string> = {
  buyer: 'Cumpărător',
  renter: 'Chiriaș',
  investor: 'Investitor',
};

const TYPE_VARIANT: Record<
  string,
  'info' | 'success' | 'warning' | 'outline'
> = {
  buyer: 'info',
  renter: 'success',
  investor: 'warning',
};

// ── Add client modal ──────────────────────────────────────────────────────────

function AddClientModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ClientCreate>({
    full_name: '',
    client_type: 'buyer',
  });

  const { data: cities = [] } = useQuery({
    queryKey: ['cities'],
    queryFn: () => api.cities(),
  });

  const mutation = useMutation({
    mutationFn: (data: ClientCreate) => api.createClient(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['clients'] });
      setForm({ full_name: '', client_type: 'buyer' });
      onClose();
    },
  });

  function update<K extends keyof ClientCreate>(
    key: K,
    value: ClientCreate[K]
  ) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.full_name.trim()) return;
    mutation.mutate(form);
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Adaugă client nou" size="lg">
      <form onSubmit={handleSubmit} className="p-6 space-y-5">
        {mutation.isError && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
            Eroare la adăugarea clientului. Verifică că backend-ul rulează.
          </div>
        )}

        {/* Name + contact */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="sm:col-span-2">
            <Input
              label="Nume complet *"
              placeholder="ex: Maria Ionescu"
              value={form.full_name}
              onChange={(e) => update('full_name', e.target.value)}
              required
            />
          </div>
          <Input
            label="Telefon"
            type="tel"
            placeholder="07xx xxx xxx"
            value={form.phone ?? ''}
            onChange={(e) =>
              update('phone', e.target.value || undefined)
            }
          />
          <Input
            label="Email"
            type="email"
            placeholder="email@exemplu.ro"
            value={form.email ?? ''}
            onChange={(e) =>
              update('email', e.target.value || undefined)
            }
          />
          <Select
            label="Tip client"
            value={form.client_type ?? 'buyer'}
            options={CLIENT_TYPES}
            onChange={(e) => update('client_type', e.target.value)}
          />
          <Select
            label="Oraș preferat"
            value={form.preferred_city_id ?? ''}
            options={cities.map((c) => ({ value: c.id, label: c.name }))}
            placeholder="Selectează oraș"
            onChange={(e) =>
              update(
                'preferred_city_id',
                e.target.value ? Number(e.target.value) : undefined
              )
            }
          />
        </div>

        {/* Budget */}
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Buget
          </p>
          <div className="grid grid-cols-2 gap-4">
            <Input
              label="Buget minim (EUR)"
              type="number"
              min={0}
              placeholder="ex: 50000"
              value={form.budget_min_eur ?? ''}
              onChange={(e) =>
                update(
                  'budget_min_eur',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
            />
            <Input
              label="Buget maxim (EUR)"
              type="number"
              min={0}
              placeholder="ex: 100000"
              value={form.budget_max_eur ?? ''}
              onChange={(e) =>
                update(
                  'budget_max_eur',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
            />
          </div>
        </div>

        {/* Property requirements */}
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest mb-3">
            Cerințe proprietate
          </p>
          <div className="grid grid-cols-3 gap-4">
            <Input
              label="Camere min"
              type="number"
              min={1}
              max={20}
              placeholder="1"
              value={form.min_rooms ?? ''}
              onChange={(e) =>
                update(
                  'min_rooms',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
            />
            <Input
              label="Camere max"
              type="number"
              min={1}
              max={20}
              placeholder="4"
              value={form.max_rooms ?? ''}
              onChange={(e) =>
                update(
                  'max_rooms',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
            />
            <Input
              label="Suprafață min (mp)"
              type="number"
              min={0}
              placeholder="40"
              value={form.min_surface_m2 ?? ''}
              onChange={(e) =>
                update(
                  'min_surface_m2',
                  e.target.value ? Number(e.target.value) : undefined
                )
              }
            />
          </div>
        </div>

        {/* Notes */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Notițe
          </label>
          <textarea
            rows={3}
            placeholder="Preferințe speciale, condiții, observații..."
            value={form.notes ?? ''}
            onChange={(e) =>
              update('notes', e.target.value || undefined)
            }
            className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-400 resize-none transition-colors"
          />
        </div>

        <div className="flex justify-end gap-3 pt-2 border-t border-gray-100">
          <Button variant="outline" type="button" onClick={onClose}>
            Anulează
          </Button>
          <Button
            type="submit"
            loading={mutation.isPending}
            disabled={!form.full_name.trim()}
          >
            <UserPlus className="w-4 h-4" />
            Adaugă client
          </Button>
        </div>
      </form>
    </Modal>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function ClientsPage() {
  const [modalOpen, setModalOpen] = useState(false);

  const {
    data: clients = [],
    isLoading,
    isError,
  } = useQuery({
    queryKey: ['clients'],
    queryFn: () => api.clients(),
  });

  const { data: cities = [] } = useQuery({
    queryKey: ['cities'],
    queryFn: () => api.cities(),
  });

  const cityMap = Object.fromEntries(cities.map((c) => [c.id, c.name]));

  return (
    <div className="space-y-5">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">
          {clients.length}{' '}
          {clients.length === 1 ? 'client' : 'clienți'} înregistrați
        </p>
        <Button onClick={() => setModalOpen(true)}>
          <UserPlus className="w-4 h-4" />
          Client nou
        </Button>
      </div>

      {/* Table card */}
      <Card>
        {isLoading ? (
          <FullPageSpinner />
        ) : isError ? (
          <div className="p-10 text-center space-y-1">
            <p className="text-sm text-red-500">
              Nu s-au putut încărca clienții.
            </p>
            <p className="text-xs text-gray-400">
              Verifică că backend-ul rulează la http://127.0.0.1:8000
            </p>
          </div>
        ) : clients.length === 0 ? (
          <EmptyState
            title="Niciun client"
            description="Adaugă primul client pentru a începe"
            icon={Users}
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100">
                  {['Client', 'Tip', 'Contact', 'Buget', 'Cerințe', 'Adăugat'].map(
                    (h) => (
                      <th
                        key={h}
                        className="text-left px-5 py-3 text-xs font-semibold text-gray-400 uppercase tracking-widest first:pl-5"
                      >
                        {h}
                      </th>
                    )
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {clients.map((client) => (
                  <tr
                    key={client.id}
                    className="hover:bg-gray-50/60 transition-colors"
                  >
                    {/* Name + city */}
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-blue-50 flex items-center justify-center shrink-0">
                          <span className="text-blue-700 text-xs font-bold">
                            {client.full_name.slice(0, 2).toUpperCase()}
                          </span>
                        </div>
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-gray-900 truncate">
                            {client.full_name}
                          </p>
                          {client.preferred_city_id && (
                            <p className="text-xs text-gray-400 flex items-center gap-1 mt-0.5">
                              <MapPin className="w-3 h-3" />
                              {cityMap[client.preferred_city_id] ??
                                `#${client.preferred_city_id}`}
                            </p>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* Type badge */}
                    <td className="px-5 py-3.5">
                      <Badge
                        variant={TYPE_VARIANT[client.client_type] ?? 'outline'}
                      >
                        {TYPE_LABEL[client.client_type] ?? client.client_type}
                      </Badge>
                    </td>

                    {/* Contact */}
                    <td className="px-5 py-3.5">
                      <div className="space-y-1">
                        {client.phone && (
                          <p className="text-xs text-gray-600 flex items-center gap-1.5">
                            <Phone className="w-3 h-3 text-gray-400" />
                            {client.phone}
                          </p>
                        )}
                        {client.email && (
                          <p className="text-xs text-gray-600 flex items-center gap-1.5">
                            <Mail className="w-3 h-3 text-gray-400" />
                            {client.email}
                          </p>
                        )}
                        {!client.phone && !client.email && (
                          <span className="text-xs text-gray-300">—</span>
                        )}
                      </div>
                    </td>

                    {/* Budget */}
                    <td className="px-5 py-3.5">
                      {client.budget_max_eur ? (
                        <div>
                          <p className="text-sm font-semibold text-gray-900">
                            {formatCurrency(client.budget_max_eur)}
                          </p>
                          {client.budget_min_eur && (
                            <p className="text-xs text-gray-400">
                              min {formatCurrency(client.budget_min_eur)}
                            </p>
                          )}
                        </div>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                    </td>

                    {/* Requirements */}
                    <td className="px-5 py-3.5">
                      <div className="text-xs text-gray-600 space-y-0.5">
                        {(client.min_rooms || client.max_rooms) && (
                          <p className="flex items-center gap-1">
                            <Home className="w-3 h-3 text-gray-400" />
                            {client.min_rooms && client.max_rooms
                              ? `${client.min_rooms}–${client.max_rooms} cam.`
                              : client.min_rooms
                              ? `min ${client.min_rooms} cam.`
                              : `max ${client.max_rooms} cam.`}
                          </p>
                        )}
                        {client.min_surface_m2 && (
                          <p>min {client.min_surface_m2} mp</p>
                        )}
                        {!client.min_rooms &&
                          !client.max_rooms &&
                          !client.min_surface_m2 && (
                            <span className="text-gray-300">Fără cerințe</span>
                          )}
                      </div>
                    </td>

                    {/* Date */}
                    <td className="px-5 py-3.5 text-xs text-gray-400 whitespace-nowrap">
                      {formatDate(client.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <AddClientModal
        isOpen={modalOpen}
        onClose={() => setModalOpen(false)}
      />
    </div>
  );
}
