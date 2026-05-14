/**
 * TanStack-Query-Hooks fuer User-Verwaltung (Sprint 9.17, AE-50).
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { usersApi } from "./users";
import type {
  User,
  UserCreate,
  UserPasswordReset,
  UserUpdate,
} from "./types";

const KEYS = {
  list: ["users"] as const,
};

export function useUsers(): UseQueryResult<User[]> {
  return useQuery({
    queryKey: KEYS.list,
    queryFn: () => usersApi.list(),
  });
}

export function useCreateUser(): UseMutationResult<User, Error, UserCreate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserCreate) => usersApi.create(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list }),
  });
}

export function useUpdateUser(
  id: number,
): UseMutationResult<User, Error, UserUpdate> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserUpdate) => usersApi.update(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list }),
  });
}

export function useResetUserPassword(
  id: number,
): UseMutationResult<User, Error, UserPasswordReset> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: UserPasswordReset) => usersApi.resetPassword(id, payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list }),
  });
}

export function useDeleteUser(): UseMutationResult<void, Error, number> {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => usersApi.remove(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEYS.list }),
  });
}
