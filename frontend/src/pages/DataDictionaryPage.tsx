import React, { useState } from 'react';
import ContentLayout from '@cloudscape-design/components/content-layout';
import Header from '@cloudscape-design/components/header';
import SpaceBetween from '@cloudscape-design/components/space-between';
import Container from '@cloudscape-design/components/container';
import ExpandableSection from '@cloudscape-design/components/expandable-section';
import Table from '@cloudscape-design/components/table';
import Box from '@cloudscape-design/components/box';
import TextFilter from '@cloudscape-design/components/text-filter';
import BreadcrumbGroup from '@cloudscape-design/components/breadcrumb-group';
import Badge from '@cloudscape-design/components/badge';
import { useNavigate } from 'react-router-dom';

interface FieldDef {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

interface EntityDef {
  table: string;
  description: string;
  softDelete: boolean;
  fields: FieldDef[];
  relationships: string[];
}

const entities: Record<string, EntityDef[]> = {
  'Office Management': [
    {
      table: 'offices',
      description: 'Physical office locations managed by the organization.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'office_number', type: 'Integer', required: true, description: 'Unique office identifier number' },
        { name: 'region_number', type: 'Integer', required: false, description: 'Regional grouping number' },
        { name: 'location_type', type: 'String(20)', required: true, description: 'Type of location (e.g., office, warehouse)' },
        { name: 'location_name', type: 'String(255)', required: true, description: 'Human-readable name of the office' },
        { name: 'manager_id', type: 'UUID (FK → managers)', required: false, description: 'Assigned manager' },
        { name: 'is_active', type: 'Boolean', required: true, description: 'Whether the office is currently active (default: true)' },
        { name: 'address_line_1', type: 'String(255)', required: false, description: 'Street address line 1' },
        { name: 'address_line_2', type: 'String(255)', required: false, description: 'Street address line 2' },
        { name: 'city', type: 'String(100)', required: false, description: 'City' },
        { name: 'state', type: 'String(2)', required: false, description: 'Two-letter state code' },
        { name: 'zip_code', type: 'String(10)', required: false, description: 'ZIP or postal code' },
        { name: 'phone_number', type: 'Text', required: false, description: 'Office phone number' },
        { name: 'fax', type: 'Text', required: false, description: 'Fax number' },
        { name: 'email', type: 'String(255)', required: false, description: 'Office email address' },
        { name: 'mail_shipping', type: 'Text', required: false, description: 'Mail/shipping information' },
        { name: 'sector', type: 'Text', required: false, description: 'Business sector classification' },
        { name: 'other_names', type: 'Text', required: false, description: 'Alternate names for the office' },
        { name: 'crown_property_on_site', type: 'Text', required: false, description: 'Crown property details' },
        { name: 'additional_info', type: 'Text', required: false, description: 'Additional information' },
        { name: 'closing_notes', type: 'Text', required: false, description: 'Notes about office closure' },
        { name: 'notes', type: 'Text', required: false, description: 'General notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: [
        'Manager (many-to-one via manager_id)',
        'Leases (one-to-many)',
        'Landlords (one-to-many)',
        'Vendors (many-to-many via vendor_offices)',
        'Transitions (one-to-many)',
        'HVAC Contracts (one-to-many)',
      ],
    },
    {
      table: 'managers',
      description: 'Office managers who oversee one or more offices.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'name', type: 'String(255)', required: true, description: 'Manager full name (unique)' },
        { name: 'email', type: 'String(255)', required: false, description: 'Manager email address' },
        { name: 'phone', type: 'Text', required: false, description: 'Manager phone number' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Offices (one-to-many)', 'Leases (one-to-many via manager_id)', 'HVAC Contracts (one-to-many via manager_id)'],
    },
    {
      table: 'leases',
      description: 'Lease agreements associated with offices.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: false, description: 'Associated office' },
        { name: 'lease_name', type: 'String(255)', required: true, description: 'Unique name/identifier for the lease' },
        { name: 'manager_id', type: 'UUID (FK → managers)', required: false, description: 'Responsible manager' },
        { name: 'lease_expiration', type: 'Date', required: false, description: 'Lease expiration date' },
        { name: 'lessor_name', type: 'Text', required: false, description: 'Name of the lessor/landlord' },
        { name: 'notice_period', type: 'String(255)', required: false, description: 'Required notice period text' },
        { name: 'notice_period_days', type: 'Integer', required: false, description: 'Notice period in days' },
        { name: 'lease_notice_date', type: 'Date', required: false, description: 'Date notice must be given by' },
        { name: 'notice_given_date', type: 'Date', required: false, description: 'Date notice was actually given' },
        { name: 'status', type: 'String(50)', required: false, description: 'Lease lifecycle status (active, pending, expired, terminated, etc.)' },
        { name: 'expiration_year', type: 'Integer', required: true, description: 'Year of lease expiration' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Office (many-to-one via office_id)', 'Manager (many-to-one via manager_id)', 'Lease Notes (one-to-many, cascade delete)'],
    },
    {
      table: 'lease_notes',
      description: 'Notes attached to individual leases.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'lease_id', type: 'UUID (FK → leases)', required: true, description: 'Parent lease (cascade delete)' },
        { name: 'note_text', type: 'Text', required: true, description: 'Note content' },
        { name: 'note_order', type: 'Integer', required: true, description: 'Display order (default: 0)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: ['Lease (many-to-one via lease_id)'],
    },
    {
      table: 'landlords',
      description: 'Landlord/property owner records linked to offices.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'ern', type: 'String(20)', required: false, description: 'External reference number' },
        { name: 'office_name', type: 'String(255)', required: false, description: 'Office name for display' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: false, description: 'Associated office' },
        { name: 'address', type: 'Text', required: false, description: 'Landlord address' },
        { name: 'landlord_company', type: 'String(255)', required: false, description: 'Landlord company name' },
        { name: 'contact_name', type: 'String(255)', required: false, description: 'Primary contact name' },
        { name: 'title', type: 'String(100)', required: false, description: 'Contact title/position' },
        { name: 'contact_email', type: 'String(255)', required: false, description: 'Contact email address' },
        { name: 'contact_phone', type: 'Text', required: false, description: 'Contact phone number' },
        { name: 'contact_mailing_address', type: 'Text', required: false, description: 'Mailing address' },
        { name: 'online_sign_in', type: 'Text', required: false, description: 'Online portal sign-in info' },
        { name: 'vendor_id', type: 'String(255)', required: false, description: 'External vendor ID reference' },
        { name: 'notes', type: 'Text', required: false, description: 'General notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: [
        'Office (many-to-one via office_id)',
        'Additional Names (one-to-many, cascade delete)',
        'Contacts (one-to-many, cascade delete)',
      ],
    },
    {
      table: 'landlord_additional_names',
      description: 'Additional names and vendor references for landlords.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'landlord_id', type: 'UUID (FK → landlords)', required: false, description: 'Parent landlord (cascade delete)' },
        { name: 'vendor_id', type: 'String(255)', required: false, description: 'External vendor ID' },
        { name: 'co_name', type: 'Text', required: false, description: 'C/O name' },
        { name: 'vendor_name', type: 'Text', required: false, description: 'Vendor name' },
        { name: 'other_names', type: 'Text', required: false, description: 'Other names' },
        { name: 'additional_names', type: 'Text', required: false, description: 'Additional names' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: ['Landlord (many-to-one via landlord_id)'],
    },
    {
      table: 'landlord_contacts',
      description: 'Additional contact persons for a landlord.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'landlord_id', type: 'UUID (FK → landlords)', required: true, description: 'Parent landlord (cascade delete)' },
        { name: 'contact_name', type: 'String(255)', required: true, description: 'Contact name' },
        { name: 'title', type: 'String(100)', required: false, description: 'Title/position' },
        { name: 'email', type: 'String(255)', required: false, description: 'Email address' },
        { name: 'phone', type: 'String(50)', required: false, description: 'Phone number' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Landlord (many-to-one via landlord_id)'],
    },
    {
      table: 'vendors',
      description: 'Service vendors that can be assigned to multiple offices.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'company_name', type: 'String(255)', required: true, description: 'Vendor company name' },
        { name: 'services', type: 'Text', required: false, description: 'Description of services provided' },
        { name: 'contact_name', type: 'String(255)', required: false, description: 'Primary contact name' },
        { name: 'contact_email', type: 'String(255)', required: false, description: 'Contact email' },
        { name: 'contact_phone', type: 'String(50)', required: false, description: 'Contact phone' },
        { name: 'address', type: 'Text', required: false, description: 'Vendor address' },
        { name: 'is_preferred', type: 'Boolean', required: true, description: 'Preferred vendor flag (default: false)' },
        { name: 'notes', type: 'Text', required: false, description: 'General notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Offices (many-to-many via vendor_offices join table)'],
    },
    {
      table: 'vendor_offices',
      description: 'Join table linking vendors to offices (many-to-many).',
      softDelete: false,
      fields: [
        { name: 'vendor_id', type: 'UUID (FK → vendors)', required: true, description: 'Vendor ID (composite PK, cascade delete)' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: true, description: 'Office ID (composite PK, cascade delete)' },
      ],
      relationships: ['Vendor (many-to-one)', 'Office (many-to-one)'],
    },
    {
      table: 'office_transitions',
      description: 'Tracks office openings, closings, relocations, and consolidations.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: false, description: 'Associated office' },
        { name: 'office_number', type: 'Integer', required: false, description: 'Office number reference' },
        { name: 'transition_type', type: 'String(20)', required: true, description: 'Type: opening, closing, relocation, consolidation' },
        { name: 'address', type: 'Text', required: false, description: 'Current address' },
        { name: 'new_address', type: 'Text', required: false, description: 'New address (for relocations)' },
        { name: 'status', type: 'String(20)', required: true, description: 'Status: in_progress, completed, cancelled (default: in_progress)' },
        { name: 'sheet_name', type: 'String(100)', required: false, description: 'Source spreadsheet sheet name' },
        { name: 'lease_expiration', type: 'Text', required: false, description: 'Lease expiration info' },
        { name: 'estimated_date', type: 'Text', required: false, description: 'Estimated transition date' },
        { name: 'notes', type: 'Text', required: false, description: 'General notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Office (many-to-one via office_id)', 'Checklist Items (one-to-many, cascade delete)'],
    },
    {
      table: 'transition_checklist_items',
      description: 'Individual checklist items within a transition.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'transition_id', type: 'UUID (FK → office_transitions)', required: true, description: 'Parent transition (cascade delete)' },
        { name: 'item_label', type: 'String(500)', required: true, description: 'Checklist item description' },
        { name: 'response', type: 'Text', required: false, description: 'Response/answer' },
        { name: 'additional_notes', type: 'Text', required: false, description: 'Additional notes' },
        { name: 'extra_notes', type: 'Text', required: false, description: 'Extra notes' },
        { name: 'sort_order', type: 'Integer', required: true, description: 'Display order (default: 0)' },
        { name: 'is_complete', type: 'Boolean', required: true, description: 'Completion flag (default: false)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Transition (many-to-one via transition_id)'],
    },
  ],
  HVAC: [
    {
      table: 'hvac_contracts',
      description: 'HVAC service contracts for offices across all locations.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: false, description: 'Associated office' },
        { name: 'office_number', type: 'Integer', required: false, description: 'Office number reference' },
        { name: 'office_name', type: 'Text', required: false, description: 'Office name for display' },
        { name: 'hvac_company', type: 'Text', required: false, description: 'HVAC contractor company' },
        { name: 'contact', type: 'Text', required: false, description: 'Contractor contact info' },
        { name: 'comments', type: 'Text', required: false, description: 'Comments' },
        { name: 'frequency', type: 'Text', required: false, description: 'Service frequency' },
        { name: 'last_serviced', type: 'Text', required: false, description: 'Last serviced date (text)' },
        { name: 'last_serviced_date', type: 'Date', required: false, description: 'Last serviced (parsed date)' },
        { name: 'next_service', type: 'Text', required: false, description: 'Next service date (text)' },
        { name: 'next_service_date', type: 'Date', required: false, description: 'Next service (parsed date)' },
        { name: 'manager_id', type: 'UUID (FK → managers)', required: false, description: 'Responsible manager' },
        { name: 'landlord_handles', type: 'Boolean', required: true, description: 'Whether landlord handles HVAC (default: false)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Office (many-to-one via office_id)', 'Manager (many-to-one via manager_id)', 'HVAC Office Details (one-to-many, cascade delete)'],
    },
    {
      table: 'hvac_office_details',
      description: 'Detailed HVAC contractor information for specific offices.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'hvac_contract_id', type: 'UUID (FK → hvac_contracts)', required: false, description: 'Parent HVAC contract (cascade delete)' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: false, description: 'Associated office' },
        { name: 'sheet_name', type: 'Text', required: false, description: 'Source sheet name' },
        { name: 'hvac_contractor', type: 'Text', required: false, description: 'Contractor name' },
        { name: 'contractor_phone', type: 'Text', required: false, description: 'Contractor phone' },
        { name: 'contractor_email', type: 'Text', required: false, description: 'Contractor email' },
        { name: 'contractor_address', type: 'Text', required: false, description: 'Contractor address' },
        { name: 'frequency', type: 'Text', required: false, description: 'Service frequency' },
        { name: 'responsibility_summary', type: 'Text', required: false, description: 'Summary of responsibilities' },
        { name: 'responsibility_detail', type: 'Text', required: false, description: 'Detailed responsibilities' },
        { name: 'lease_expiration', type: 'Date', required: false, description: 'Lease expiration date' },
        { name: 'lease_expiration_text', type: 'Text', required: false, description: 'Lease expiration (text)' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['HVAC Contract (many-to-one via hvac_contract_id)'],
    },
    {
      table: 'hq_heat_pumps',
      description: 'HQ building heat pump inventory.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'unit_id', type: 'String(10)', required: true, description: 'Unit identifier (unique)' },
        { name: 'location_desc', type: 'String(255)', required: false, description: 'Location description' },
        { name: 'make', type: 'String(100)', required: false, description: 'Manufacturer' },
        { name: 'model', type: 'String(150)', required: false, description: 'Model number' },
        { name: 'serial_number', type: 'String(100)', required: false, description: 'Serial number' },
        { name: 'install_year', type: 'Integer', required: false, description: 'Year installed' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Service Logs (one-to-many, cascade delete)'],
    },
    {
      table: 'hq_heat_pump_service_logs',
      description: 'Service history records for HQ heat pumps.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'heat_pump_id', type: 'UUID (FK → hq_heat_pumps)', required: true, description: 'Parent heat pump (cascade delete)' },
        { name: 'service_date', type: 'Date', required: false, description: 'Date of service' },
        { name: 'invoice_number', type: 'String(255)', required: false, description: 'Invoice number' },
        { name: 'cost', type: 'Numeric(10,2)', required: false, description: 'Service cost' },
        { name: 'description', type: 'Text', required: true, description: 'Service description' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: ['Heat Pump (many-to-one via heat_pump_id)'],
    },
    {
      table: 'hq_hvac_issues',
      description: 'HQ HVAC issues and repairs.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'issue_date', type: 'Date', required: false, description: 'Date of issue' },
        { name: 'description', type: 'Text', required: true, description: 'Issue description' },
        { name: 'invoice_number', type: 'String(255)', required: false, description: 'Invoice number' },
        { name: 'cost', type: 'Numeric(10,2)', required: false, description: 'Repair cost' },
        { name: 'status', type: 'String(20)', required: true, description: 'Status: open, resolved (default: open)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: [],
    },
    {
      table: 'hq_pm_tasks',
      description: 'Preventive maintenance task definitions for HQ equipment.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'equipment_category', type: 'String(30)', required: true, description: 'Category: heat_pumps, boilers, chillers, cooling_towers, other' },
        { name: 'equipment_id', type: 'String(255)', required: false, description: 'Equipment identifier' },
        { name: 'task_description', type: 'Text', required: true, description: 'PM task description' },
        { name: 'frequency', type: 'String(30)', required: false, description: 'Task frequency' },
        { name: 'can_in_house', type: 'Boolean', required: true, description: 'Can be done in-house (default: false)' },
        { name: 'last_pm_date', type: 'Date', required: false, description: 'Last PM completion date' },
        { name: 'next_due_date', type: 'Date', required: false, description: 'Next PM due date' },
        { name: 'status', type: 'String(30)', required: true, description: 'Status: Not Started, In Progress, Completed' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: [],
    },
    {
      table: 'hq_pm_logs',
      description: 'Log entries for completed preventive maintenance visits.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'timestamp', type: 'DateTime', required: false, description: 'Log timestamp' },
        { name: 'tech_name', type: 'String(255)', required: false, description: 'Technician name' },
        { name: 'date_of_visit', type: 'Date', required: false, description: 'Visit date' },
        { name: 'location', type: 'String(255)', required: false, description: 'Location within HQ' },
        { name: 'equipment_type', type: 'String(255)', required: false, description: 'Equipment type' },
        { name: 'equipment_id', type: 'String(255)', required: false, description: 'Equipment ID' },
        { name: 'task', type: 'Text', required: false, description: 'Task performed' },
        { name: 'status', type: 'String(30)', required: false, description: 'Completion status' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: [],
    },
    {
      table: 'hq_maintenance_contracts',
      description: 'HQ maintenance service contracts.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'contractor_name', type: 'String(255)', required: false, description: 'Contractor name' },
        { name: 'contract_start_date', type: 'Date', required: false, description: 'Contract start date' },
        { name: 'cancellation_notice', type: 'String(100)', required: false, description: 'Cancellation notice period' },
        { name: 'equipment_covered', type: 'Text', required: false, description: 'Equipment covered by contract' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Visits (one-to-many, cascade delete)'],
    },
    {
      table: 'hq_maintenance_visits',
      description: 'Visit records for HQ maintenance contracts.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'contract_id', type: 'UUID (FK → hq_maintenance_contracts)', required: false, description: 'Parent contract (cascade delete)' },
        { name: 'visit_date', type: 'Date', required: false, description: 'Visit date' },
        { name: 'invoice_number', type: 'String(255)', required: false, description: 'Invoice number' },
        { name: 'cost', type: 'Numeric(10,2)', required: false, description: 'Visit cost' },
        { name: 'tech_name', type: 'String(255)', required: false, description: 'Technician name' },
        { name: 'description', type: 'Text', required: false, description: 'Description' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: ['Contract (many-to-one via contract_id)'],
    },
    {
      table: 'hq_tower_spray_logs',
      description: 'Cooling tower spray treatment log entries.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'entry_date', type: 'Date', required: false, description: 'Entry date' },
        { name: 'invoice_number', type: 'String(255)', required: false, description: 'Invoice number' },
        { name: 'cost', type: 'Numeric(10,2)', required: false, description: 'Cost' },
        { name: 'description', type: 'Text', required: true, description: 'Description' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: [],
    },
    {
      table: 'hq_backflows',
      description: 'Backflow preventer inventory and testing records.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'location_desc', type: 'Text', required: true, description: 'Location description' },
        { name: 'replaced_year', type: 'String(20)', required: false, description: 'Year replaced' },
        { name: 'last_tested_by', type: 'String(255)', required: false, description: 'Last tested by (company/person)' },
        { name: 'last_tested_year', type: 'String(20)', required: false, description: 'Year last tested' },
        { name: 'reported_to', type: 'String(255)', required: false, description: 'Reported to authority' },
        { name: 'notes', type: 'Text', required: false, description: 'Notes' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: [],
    },
  ],
  Maintenance: [
    {
      table: 'ticket_categories',
      description: 'Categories for classifying maintenance tickets.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'name', type: 'String(255)', required: true, description: 'Category name (unique)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Maintenance Tickets (one-to-many)'],
    },
    {
      table: 'maintenance_tickets',
      description: 'Maintenance work orders submitted by users.',
      softDelete: true,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'subject', type: 'String(255)', required: true, description: 'Ticket subject line' },
        { name: 'priority', type: 'String(20)', required: true, description: 'Priority: low, medium, high, critical' },
        { name: 'status', type: 'String(20)', required: true, description: 'Status: open, in_progress, resolved, closed (default: open)' },
        { name: 'category_id', type: 'UUID (FK → ticket_categories)', required: true, description: 'Ticket category' },
        { name: 'office_id', type: 'UUID (FK → offices)', required: true, description: 'Office where issue exists' },
        { name: 'location_hours', type: 'Text', required: false, description: 'Location hours/availability' },
        { name: 'description', type: 'Text', required: true, description: 'Detailed issue description' },
        { name: 'created_by_id', type: 'UUID (FK → users)', required: true, description: 'User who created the ticket' },
        { name: 'assigned_to_id', type: 'UUID (FK → managers)', required: false, description: 'Assigned manager' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: [
        'Category (many-to-one via category_id)',
        'Office (many-to-one via office_id)',
        'Created By User (many-to-one via created_by_id)',
        'Assigned To Manager (many-to-one via assigned_to_id)',
        'Ticket Notes (one-to-many, cascade delete)',
      ],
    },
    {
      table: 'ticket_notes',
      description: 'Notes and updates on maintenance tickets.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'ticket_id', type: 'UUID (FK → maintenance_tickets)', required: true, description: 'Parent ticket (cascade delete)' },
        { name: 'note_text', type: 'Text', required: true, description: 'Note content' },
        { name: 'note_order', type: 'Integer', required: true, description: 'Display order (default: 0)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
      ],
      relationships: ['Maintenance Ticket (many-to-one via ticket_id)'],
    },
  ],
  System: [
    {
      table: 'users',
      description: 'Application users with authentication and role-based access.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'email', type: 'String(255)', required: true, description: 'Email address (unique)' },
        { name: 'display_name', type: 'String(255)', required: true, description: 'Display name' },
        { name: 'password_hash', type: 'String(255)', required: false, description: 'Hashed password (internal auth)' },
        { name: 'auth_provider', type: 'String(20)', required: true, description: 'Auth provider: internal, google (default: internal)' },
        { name: 'google_sub', type: 'String(255)', required: false, description: 'Google OAuth subject ID (unique)' },
        { name: 'role', type: 'String(20)', required: true, description: 'Role: admin, editor, viewer, accountant (default: viewer)' },
        { name: 'is_active', type: 'Boolean', required: true, description: 'Whether the user account is active (default: true)' },
        { name: 'last_login_at', type: 'DateTime', required: false, description: 'Last login timestamp' },
        { name: 'preferences', type: 'JSONB', required: false, description: 'User preferences (key-value)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Maintenance Tickets (one-to-many as creator)', 'Activity Logs (one-to-many)'],
    },
    {
      table: 'attachments',
      description: 'File attachments linked to any entity via entity_type/entity_id polymorphic pattern.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'entity_type', type: 'String(50)', required: true, description: 'Type of parent entity (e.g., office, lease, vendor)' },
        { name: 'entity_id', type: 'UUID', required: true, description: 'ID of parent entity' },
        { name: 'original_filename', type: 'String(255)', required: true, description: 'Original uploaded filename' },
        { name: 'stored_filename', type: 'String(255)', required: true, description: 'Stored filename on disk (unique)' },
        { name: 'content_type', type: 'String(100)', required: true, description: 'MIME content type' },
        { name: 'file_size', type: 'Integer', required: true, description: 'File size in bytes' },
        { name: 'uploaded_by', type: 'String(255)', required: true, description: 'Uploader display name' },
        { name: 'description', type: 'Text', required: false, description: 'File description' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Polymorphic: linked to any entity via entity_type + entity_id'],
    },
    {
      table: 'activity_logs',
      description: 'Audit trail of all user actions across all entities.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'user_id', type: 'UUID (FK → users)', required: true, description: 'User who performed the action' },
        { name: 'user_display_name', type: 'String(255)', required: true, description: 'User display name at time of action' },
        { name: 'action', type: 'String(50)', required: true, description: 'Action type: created, updated, deleted, status_changed' },
        { name: 'entity_type', type: 'String(50)', required: true, description: 'Type of entity affected' },
        { name: 'entity_id', type: 'UUID', required: true, description: 'ID of entity affected' },
        { name: 'entity_label', type: 'String(255)', required: true, description: 'Human-readable entity label at time of action' },
        { name: 'changes', type: 'JSONB', required: false, description: 'JSON diff of changed fields' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Timestamp of action' },
      ],
      relationships: ['User (many-to-one via user_id)'],
    },
    {
      table: 'email_reminder_rules',
      description: 'Automated email reminder rules for lease and other notifications.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'rule_name', type: 'String(255)', required: true, description: 'Rule name' },
        { name: 'rule_type', type: 'String(30)', required: true, description: 'Rule type (e.g., lease_expiration)' },
        { name: 'days_before', type: 'Integer', required: true, description: 'Days before event to send reminder' },
        { name: 'recipient_emails', type: 'Array(String)', required: true, description: 'List of recipient email addresses' },
        { name: 'is_active', type: 'Boolean', required: true, description: 'Whether rule is active (default: true)' },
        { name: 'last_triggered_at', type: 'DateTime', required: false, description: 'Last time rule triggered' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['Email Logs (one-to-many via rule_id)'],
    },
    {
      table: 'email_logs',
      description: 'Log of all emails sent by the system.',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'rule_id', type: 'UUID (FK → email_reminder_rules)', required: false, description: 'Associated reminder rule' },
        { name: 'sent_to', type: 'String(255)', required: true, description: 'Recipient email' },
        { name: 'subject', type: 'String(500)', required: true, description: 'Email subject' },
        { name: 'body', type: 'Text', required: false, description: 'Email body' },
        { name: 'sent_at', type: 'DateTime', required: true, description: 'Timestamp sent' },
        { name: 'status', type: 'String(20)', required: true, description: 'Status: sent, failed (default: sent)' },
      ],
      relationships: ['Email Reminder Rule (many-to-one via rule_id)'],
    },
    {
      table: 'support_requests',
      description: 'In-app support requests submitted by users. Surfaced on the Administration → Support Requests page, where admins can review them and forward them to the configured support email (site_settings.support_email).',
      softDelete: false,
      fields: [
        { name: 'id', type: 'UUID', required: true, description: 'Primary key' },
        { name: 'organization_id', type: 'UUID (FK → organizations)', required: false, description: 'Owning organization' },
        { name: 'subject', type: 'String(255)', required: true, description: 'Short summary of the request' },
        { name: 'message', type: 'Text', required: true, description: 'Full request details' },
        { name: 'status', type: 'String(20)', required: true, description: 'Lifecycle status: open or resolved (default: open)' },
        { name: 'requester_user_id', type: 'UUID (FK → users)', required: false, description: 'Submitting user (set null on delete)' },
        { name: 'requester_name', type: 'String(255)', required: false, description: 'Submitter display name (snapshot)' },
        { name: 'requester_email', type: 'String(320)', required: false, description: 'Submitter email (snapshot)' },
        { name: 'created_at', type: 'DateTime', required: true, description: 'Record creation timestamp' },
        { name: 'updated_at', type: 'DateTime', required: true, description: 'Last update timestamp' },
      ],
      relationships: ['User (many-to-one via requester_user_id)', 'Organization (many-to-one via organization_id)'],
    },
  ],
};

const COLUMN_DEFS = [
  { id: 'name', header: 'Field', cell: (f: FieldDef) => <Box fontWeight={f.required ? 'bold' : 'normal'}><code>{f.name}</code></Box>, width: 200 },
  { id: 'type', header: 'Type', cell: (f: FieldDef) => <code>{f.type}</code>, width: 180 },
  { id: 'required', header: 'Required', cell: (f: FieldDef) => f.required ? 'Yes' : 'No', width: 80 },
  { id: 'description', header: 'Description', cell: (f: FieldDef) => f.description },
];

const DataDictionaryPage: React.FC = () => {
  const navigate = useNavigate();
  const [filterText, setFilterText] = useState('');

  const matchesFilter = (entity: EntityDef) => {
    if (!filterText) return true;
    const t = filterText.toLowerCase();
    return (
      entity.table.toLowerCase().includes(t) ||
      entity.description.toLowerCase().includes(t) ||
      entity.fields.some(
        (f) =>
          f.name.toLowerCase().includes(t) ||
          f.type.toLowerCase().includes(t) ||
          f.description.toLowerCase().includes(t),
      )
    );
  };

  return (
    <ContentLayout
      header={
        <SpaceBetween size="m">
          <BreadcrumbGroup
            items={[{ text: 'Data Dictionary', href: '/data-dictionary' }]}
            onFollow={(e) => { e.preventDefault(); navigate(e.detail.href); }}
          />
          <Header variant="h1" description="Complete reference of all database entities, fields, types, and relationships.">
            Data Dictionary
          </Header>
        </SpaceBetween>
      }
    >
      <SpaceBetween size="l">
        <TextFilter
          filteringText={filterText}
          onChange={({ detail }) => setFilterText(detail.filteringText)}
          filteringPlaceholder="Search tables, fields, or descriptions..."
        />

        {Object.entries(entities).map(([section, sectionEntities]) => {
          const filtered = sectionEntities.filter(matchesFilter);
          if (filtered.length === 0) return null;
          return (
            <Container key={section} header={<Header variant="h2">{section}</Header>}>
              <SpaceBetween size="l">
                {filtered.map((entity) => (
                  <ExpandableSection
                    key={entity.table}
                    variant="default"
                    headerText={
                      <SpaceBetween direction="horizontal" size="xs">
                        <span><code>{entity.table}</code></span>
                        {entity.softDelete && <Badge color="blue">Soft Delete</Badge>}
                      </SpaceBetween>
                    }
                    headerDescription={entity.description}
                  >
                    <SpaceBetween size="m">
                      <Table
                        columnDefinitions={COLUMN_DEFS}
                        items={entity.fields}
                        variant="embedded"
                        wrapLines
                      />
                      {entity.relationships.length > 0 && (
                        <div>
                          <Box variant="awsui-key-label">Relationships</Box>
                          <ul style={{ margin: '4px 0 0 16px', padding: 0 }}>
                            {entity.relationships.map((r, i) => (
                              <li key={i}>{r}</li>
                            ))}
                          </ul>
                        </div>
                      )}
                    </SpaceBetween>
                  </ExpandableSection>
                ))}
              </SpaceBetween>
            </Container>
          );
        })}
      </SpaceBetween>
    </ContentLayout>
  );
};

export default DataDictionaryPage;
