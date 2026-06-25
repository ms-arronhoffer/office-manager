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

  // Users
  http.get(`${API}/users`, () => {
    return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 50, total_pages: 0 });
  }),
];
