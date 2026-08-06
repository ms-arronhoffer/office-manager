import type { User } from '@/types';

export type UserRole = User['role'];

/** Operational records may be created or edited only by Admin and Editor. */
export const canMutateOperationalData = (role: UserRole | null | undefined): boolean =>
  role === 'admin' || role === 'editor';

export const canDeleteOperationalData = (role: UserRole | null | undefined): boolean =>
  role === 'admin';

export const canManageFinance = (role: UserRole | null | undefined): boolean =>
  role === 'admin' || role === 'accountant';

export const isReadOnlyRole = (role: UserRole | null | undefined): boolean =>
  role === 'viewer';
