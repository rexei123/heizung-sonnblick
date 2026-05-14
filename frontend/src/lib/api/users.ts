/**
 * User-Verwaltung-API (Sprint 9.17, AE-50). Admin-only.
 */

import { apiClient } from "./client";
import type {
  User,
  UserCreate,
  UserPasswordReset,
  UserUpdate,
} from "./types";

const BASE = "/api/v1/users";

export const usersApi = {
  list: (): Promise<User[]> => apiClient.get<User[]>(BASE),

  create: (payload: UserCreate): Promise<User> =>
    apiClient.post<User>(BASE, payload),

  update: (id: number, payload: UserUpdate): Promise<User> =>
    apiClient.patch<User>(`${BASE}/${id}`, payload),

  resetPassword: (id: number, payload: UserPasswordReset): Promise<User> =>
    apiClient.post<User>(`${BASE}/${id}/reset-password`, payload),

  remove: (id: number): Promise<void> =>
    apiClient.delete<void>(`${BASE}/${id}`),
};
