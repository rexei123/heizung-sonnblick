/**
 * Auth-API (Sprint 9.17, AE-50).
 *
 * Cookie-based — JWT landet als HttpOnly-Cookie nach /login, kein
 * Token-Storage im Frontend noetig. `apiClient` setzt
 * `credentials: 'include'` damit der Cookie bei jedem Folge-Request
 * mitgeht.
 */

import { apiClient } from "./client";
import type {
  ChangePasswordRequest,
  LoginRequest,
  LoginResponse,
  User,
} from "./types";

const BASE = "/api/v1/auth";

export const authApi = {
  login: (payload: LoginRequest): Promise<LoginResponse> =>
    apiClient.post<LoginResponse>(`${BASE}/login`, payload),

  logout: (): Promise<void> => apiClient.post<void>(`${BASE}/logout`, {}),

  me: (): Promise<User> => apiClient.get<User>(`${BASE}/me`),

  changePassword: (payload: ChangePasswordRequest): Promise<User> =>
    apiClient.post<User>(`${BASE}/change-password`, payload),
};
