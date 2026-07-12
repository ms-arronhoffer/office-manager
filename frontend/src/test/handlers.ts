import { http, HttpResponse } from 'msw';

const API = '/api/v1';

export const handlers = [
  // Auth
  http.post(`${API}/auth/login`, () => {
    return HttpResponse.json({ access_token: 'test-token', token_type: 'bearer' });
  }),

  http.get(`${API}/auth/me`, () => {
    return HttpResponse.json({
      id: '00000000-0000-0000-0000-000000000001',
      email: 'admin@test.com',
      display_name: 'Test Admin',
      auth_provider: 'internal',
      role: 'admin',
      is_active: true,
      last_login_at: null,
      created_at: '2024-01-01T00:00:00Z',
    });
  }),

  // Offices
  http.get(`${API}/offices`, () => {
    return HttpResponse.json({
      items: [
        {
          id: '10000000-0000-0000-0000-000000000001',
          office_number: 100,
          region_number: 1,
          location_type: 'office',
          location_name: 'Main Office',
          manager: null,
          is_active: true,
          mail_shipping: null,
          notes: null,
          address_line_1: '123 Main St',
          address_line_2: null,
          city: 'Springfield',
          state: 'IL',
          zip_code: '62701',
          phone_number: null,
          fax: null,
          email: null,
          other_names: null,
          sector: null,
          crown_property_on_site: null,
          additional_info: null,
          closing_notes: null,
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    });
  }),

  // Maintenance Tickets
  http.get(`${API}/maintenance-tickets`, () => {
    return HttpResponse.json({
      items: [
        {
          id: '20000000-0000-0000-0000-000000000001',
          subject: 'Broken pipe',
          priority: 'high',
          status: 'open',
          category_id: '30000000-0000-0000-0000-000000000001',
          category: { id: '30000000-0000-0000-0000-000000000001', name: 'Plumbing', created_at: '2024-01-01T00:00:00Z' },
          office_id: '10000000-0000-0000-0000-000000000001',
          office: {
            id: '10000000-0000-0000-0000-000000000001',
            office_number: 100,
            region_number: 1,
            location_type: 'office',
            location_name: 'Main Office',
            manager: null,
            is_active: true,
            mail_shipping: null, notes: null,
            address_line_1: null, address_line_2: null,
            city: null, state: null, zip_code: null,
            phone_number: null, fax: null, email: null,
            other_names: null, sector: null,
            crown_property_on_site: null, additional_info: null, closing_notes: null,
            created_at: '2024-01-01T00:00:00Z', updated_at: '2024-01-01T00:00:00Z',
          },
          location_hours: null,
          description: 'Water leaking',
          created_by_id: '00000000-0000-0000-0000-000000000001',
          created_by: {
            id: '00000000-0000-0000-0000-000000000001',
            email: 'admin@test.com',
            display_name: 'Test Admin',
            auth_provider: 'internal',
            role: 'admin',
            is_active: true,
            last_login_at: null,
            created_at: '2024-01-01T00:00:00Z',
          },
          assigned_to_id: null,
          assigned_to: null,
          notes: [],
          created_at: '2024-01-01T00:00:00Z',
          updated_at: '2024-01-01T00:00:00Z',
        },
      ],
      total: 1,
      page: 1,
      page_size: 50,
      total_pages: 1,
    });
  }),

  // Managers
  http.get(`${API}/managers`, () => {
    return HttpResponse.json([]);
  }),

  // Ticket Categories
  http.get(`${API}/ticket-categories`, () => {
    return HttpResponse.json([
      { id: '30000000-0000-0000-0000-000000000001', name: 'Plumbing', created_at: '2024-01-01T00:00:00Z' },
    ]);
  }),

  // Dashboard
  http.get(`${API}/dashboard/summary`, () => {
    return HttpResponse.json({
      total_offices: 10,
      active_offices: 8,
      inactive_offices: 2,
      active_leases: 5,
      upcoming_expirations_90d: 2,
      overdue_notices: 1,
    });
  }),

  // Search
  http.get(`${API}/search`, () => {
    return HttpResponse.json([]);
  }),

  // Rent roll
  http.get(`${API}/leases/rent-roll`, () => {
    return HttpResponse.json({
      rows: [
        {
          lease_id: '40000000-0000-0000-0000-000000000001',
          lease_name: 'Downtown HQ',
          office_id: '10000000-0000-0000-0000-000000000001',
          office_name: 'Main Office',
          lessor_name: 'Acme Holdings',
          lease_expiration: '2027-06-30',
          days_to_expiration: 400,
          payment_amount: 10000,
          payment_frequency: 'monthly',
          monthly_rent: 10000,
          annual_rent: 120000,
          annual_escalation_rate: 0.03,
          lease_classification: 'operating',
          currency: 'USD',
          manager_name: 'Jane Doe',
        },
      ],
      total_monthly: 10000,
      total_annual: 120000,
      count: 1,
    });
  }),

  // Lease accounting portfolio
  http.get(`${API}/reports/lease-accounting-portfolio`, () => {
    return HttpResponse.json({
      leases: [
        {
          lease_id: '40000000-0000-0000-0000-000000000001',
          lease_name: 'Downtown HQ',
          office_name: 'Main Office',
          accounting_standard: 'ASC842',
          lease_classification: 'operating',
          initial_rou_asset: 500000,
          initial_lease_liability: 500000,
          remaining_rou: 450000,
          remaining_liability: 460000,
          ibr_annual: 0.05,
          remaining_months: 54,
          currency: 'USD',
        },
      ],
      total_rou: 450000,
      total_current_liability: 100000,
      total_noncurrent_liability: 360000,
      weighted_avg_ibr: 0.05,
      weighted_avg_remaining_months: 54,
    });
  }),

  // Operating expense variance
  http.get(`${API}/operating-expenses/variance`, () => {
    return HttpResponse.json([
      { year: 2025, category: 'CAM', budgeted: 50000, actual: 55000, variance: 5000 },
      { year: 2025, category: 'Taxes', budgeted: 30000, actual: 28000, variance: -2000 },
    ]);
  }),

  // Lease risk buckets
  http.get(`${API}/dashboard/lease-risk`, () => {
    return HttpResponse.json([
      { bucket: 'expired', count: 0 },
      { bucket: 'critical', count: 1 },
      { bucket: 'warning', count: 2 },
      { bucket: 'healthy', count: 5 },
    ]);
  }),

  // Users
  http.get(`${API}/users`, () => {
    return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 });
  }),

  // Primary categories
  http.get(`${API}/organizations/me/categories`, () => {
    return HttpResponse.json({
      catalog: ['commercial', 'residential', 'self_storage'],
      labels: {
        commercial: 'Commercial',
        residential: 'Residential',
        self_storage: 'Self Storage',
      },
      enabled_categories: ['commercial', 'residential'],
      overrides: {},
      effective: ['commercial', 'residential'],
    });
  }),

  http.put(`${API}/organizations/me/categories`, async ({ request }) => {
    const body = (await request.json()) as { enabled_categories: string[] };
    const enabled = body.enabled_categories;
    return HttpResponse.json({
      catalog: ['commercial', 'residential', 'self_storage'],
      labels: {
        commercial: 'Commercial',
        residential: 'Residential',
        self_storage: 'Self Storage',
      },
      enabled_categories: enabled,
      overrides: {},
      effective: enabled,
    });
  }),

  // Self storage
  http.get(`${API}/self-storage/occupancy-summary`, () => {
    return HttpResponse.json({
      total_units: 10,
      occupied_units: 6,
      available_units: 4,
      physical_occupancy_pct: 60,
      economic_occupancy_pct: 55,
      potential_monthly_revenue: '1000.00',
      in_place_monthly_revenue: '900.00',
      currency: 'USD',
    });
  }),

  http.get(`${API}/self-storage/facilities`, () => HttpResponse.json([])),
  http.get(`${API}/self-storage/managers`, () => HttpResponse.json([])),
  http.get(`${API}/self-storage/units`, () => HttpResponse.json([])),
  http.get(`${API}/self-storage/agreements`, () => HttpResponse.json([])),
  http.get(`${API}/self-storage/reservations`, () => HttpResponse.json([])),
  http.get(`${API}/self-storage/rate-plans`, () => HttpResponse.json([])),
];
