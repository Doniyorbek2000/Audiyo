"use client";

import { createContext, useContext } from "react";
import type { User } from "@/lib/types";

export const UserCtx = createContext<{ user: User | null; refresh: () => Promise<void> }>({
  user: null,
  refresh: async () => {},
});
export const useUser = () => useContext(UserCtx);
