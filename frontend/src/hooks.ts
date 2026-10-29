import { useQuery } from "@tanstack/react-query";

import { api } from "./api";
import type { Cluster, CustomField, Page, ReferenceValue, School, StaffUser } from "./types";

export function useClusters(enabled = true) {
  return useQuery({ queryKey: ["clusters"], queryFn: () => api<Cluster[]>("/api/clusters"), enabled });
}

export function useReference(list: "designation" | "subject" | "class" | "qualification") {
  return useQuery({ queryKey: ["reference", list], queryFn: () => api<ReferenceValue[]>(`/api/reference/${list}`) });
}

export function useCustomFields(entity: "teacher" | "school") {
  return useQuery({ queryKey: ["custom-fields", entity], queryFn: () => api<CustomField[]>(`/api/custom-fields/${entity}`) });
}

export function useClusterHeads(enabled: boolean) {
  return useQuery({
    queryKey: ["cluster-heads"],
    queryFn: () => api<StaffUser[]>("/api/cluster-heads"),
    enabled,
  });
}

/** Every active school in scope, for pickers. Fetched page by page (at most 200 per page). */
export function useAllSchools(enabled = true) {
  return useQuery({
    queryKey: ["schools", "all-active"],
    enabled,
    queryFn: async () => {
      const all: School[] = [];
      for (let page = 1; ; page++) {
        const chunk = await api<Page<School>>(`/api/schools?status=active&page_size=200&page=${page}`);
        all.push(...chunk.items);
        if (all.length >= chunk.total || chunk.items.length === 0) return all;
      }
    },
  });
}
