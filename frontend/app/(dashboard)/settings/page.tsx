import { Card, CardContent, CardHeader } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Building2, Shield, Bell, Puzzle } from 'lucide-react';

const SECTIONS = [
  {
    icon: Building2,
    title: 'Agenție',
    description:
      'Gestionează informațiile despre agenție: logo, denumire, date de contact.',
  },
  {
    icon: Shield,
    title: 'Utilizatori & Roluri',
    description:
      'Invită colegi și gestionează roluri: owner, manager, agent imobiliar.',
  },
  {
    icon: Bell,
    title: 'Notificări',
    description:
      'Configurează alertele automate pentru oportunități noi detectate.',
  },
  {
    icon: Puzzle,
    title: 'Integrări',
    description:
      'Conectează surse externe de anunțuri și servicii terțe (email, CRM).',
  },
];

export default function SettingsPage() {
  return (
    <div className="space-y-5 max-w-2xl">
      <div className="grid grid-cols-1 gap-3">
        {SECTIONS.map((s) => {
          const Icon = s.icon;
          return (
            <Card key={s.title}>
              <CardContent>
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-xl bg-gray-100 flex items-center justify-center shrink-0">
                    <Icon className="w-5 h-5 text-gray-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-sm font-semibold text-gray-900">
                        {s.title}
                      </h3>
                      <Badge variant="outline">În curând</Badge>
                    </div>
                    <p className="text-sm text-gray-500">{s.description}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {/* Connection info */}
      <Card>
        <CardHeader>
          <h3 className="text-sm font-semibold text-gray-900">
            Conexiune API
          </h3>
        </CardHeader>
        <CardContent>
          <div className="space-y-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Backend URL</span>
              <code className="text-xs bg-gray-100 px-2 py-1 rounded-md text-gray-700">
                http://127.0.0.1:8000
              </code>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Organization ID</span>
              <code className="text-xs bg-gray-100 px-2 py-1 rounded-md text-gray-700">
                1
              </code>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">Autentificare</span>
              <Badge variant="warning">Neimplementată</Badge>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-500">CORS</span>
              <Badge variant="success">Proxy Next.js activ</Badge>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
