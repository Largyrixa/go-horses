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
    // Falha de rede (status 0) ou erro 5xx não significa sessão inválida: tenta de novo antes de
    // tratar o usuário como deslogado. Só o 401 encerra a sessão (tratado em api.js).
    let cancelled = false, timer;
    const check = (attempt) =>
      api.me()
        .then((u) => { if (!cancelled) { setUser(u); setLoading(false); } })
        .catch((e) => {
          if (cancelled) return;
          const transient = e.status === 0 || e.status >= 500;
          if (transient && attempt < 3 && getToken()) timer = setTimeout(() => check(attempt + 1), 1500 * (attempt + 1));
          else setLoading(false);
        });
    check(0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, []);

  const login = useCallback(async (email, password) => {
    const r = await api.login({ email, password });
    setToken(r.token);
    setUser(r.user);
    return r.user;
  }, []);
  const register = useCallback((data) => api.register(data), []);
  const logout = useCallback(() => {
    const token = getToken();
    setToken(null); setUser(null);
    if (token) api.logout(token).catch(() => {}); // encerra a sessão no servidor; a local já acabou
  }, []);

  return <Ctx.Provider value={{ user, loading, login, register, logout }}>{children}</Ctx.Provider>;
}

// RF04: páginas protegidas mandam para o login e voltam para onde o usuário estava.
export function useRequireAuth() {
  const auth = useAuth();
  const navigate = useNavigate();
  const { pathname, search } = useLocation();
  const path = pathname + search;
  useEffect(() => {
    if (!auth.loading && !auth.user) navigate(`/login?next=${encodeURIComponent(path)}`, { replace: true });
  }, [auth.loading, auth.user, path, navigate]);
  return auth;
}

// Login e cadastro: quem já está logado não vê o formulário de novo; segue para `next` (ou a home).
export function useRedirectIfLogged(next = "/") {
  const auth = useAuth();
  const navigate = useNavigate();
  useEffect(() => {
    if (!auth.loading && auth.user) navigate(next, { replace: true });
  }, [auth.loading, auth.user, next, navigate]);
  return auth;
}
