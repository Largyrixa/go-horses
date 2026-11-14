import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api, getToken, setToken, setUnauthorizedHandler } from "@/lib/api";
import { toast } from "@/utils/alerts";

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setUnauthorizedHandler(() => { setUser(null); toast("warning", "Sua sessão expirou. Entre novamente."); });
    if (!getToken()) { setLoading(false); return; }
    api.me().then(setUser).catch(() => {}).finally(() => setLoading(false));
  }, []);

  const login = useCallback(async (email, password) => {
    const r = await api.login({ email, password });
    setToken(r.token);
    setUser(r.user);
    return r.user;
  }, []);
  const register = useCallback((data) => api.register(data), []);
  const logout = useCallback(() => { api.logout().catch(() => {}); setToken(null); setUser(null); }, []);

  return <Ctx.Provider value={{ user, loading, login, register, logout }}>{children}</Ctx.Provider>;
}

// RF04: páginas protegidas mandam para o login e voltam para onde o usuário estava.
export function useRequireAuth() {
  const auth = useAuth();
  const navigate = useNavigate();
  const path = useLocation().pathname;
  useEffect(() => {
    if (!auth.loading && !auth.user) navigate(`/login?next=${encodeURIComponent(path)}`, { replace: true });
  }, [auth.loading, auth.user, path, navigate]);
  return auth;
}
