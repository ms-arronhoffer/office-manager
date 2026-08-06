import { describe, expect, it } from 'vitest';
import {
  canDeleteOperationalData,
  canManageFinance,
  canMutateOperationalData,
  isReadOnlyRole,
} from '@/auth/permissions';

describe('role permissions', () => {
  it.each([
    ['admin', true],
    ['editor', true],
    ['accountant', false],
    ['viewer', false],
    [undefined, false],
  ] as const)('allows operational mutations for %s: %s', (role, expected) => {
    expect(canMutateOperationalData(role)).toBe(expected);
  });

  it('reserves operational deletion for admins', () => {
    expect(canDeleteOperationalData('admin')).toBe(true);
    expect(canDeleteOperationalData('editor')).toBe(false);
    expect(canDeleteOperationalData('viewer')).toBe(false);
  });

  it('allows finance access only for admins and accountants', () => {
    expect(canManageFinance('admin')).toBe(true);
    expect(canManageFinance('accountant')).toBe(true);
    expect(canManageFinance('editor')).toBe(false);
    expect(canManageFinance('viewer')).toBe(false);
  });

  it('recognizes only Viewer as read-only', () => {
    expect(isReadOnlyRole('viewer')).toBe(true);
    expect(isReadOnlyRole('admin')).toBe(false);
    expect(isReadOnlyRole(undefined)).toBe(false);
  });
});
