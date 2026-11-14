import { useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import Button from "@/components/Button";
import { ErrorNote, Field, PageTitle } from "@/components/ui";
import { safeNext } from "@/utils/format";

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true); setError(null);
    try {
      await login(email.trim(), password);
      navigate(safeNext(new URLSearchParams(window.location.search).get("next")));
    } catch (err) {
      setError(err.status === 401 ? "E-mail ou senha incorretos." : err.message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>Entrar</PageTitle>
      <form onSubmit={submit} className="panel flex flex-col gap-5">
        <Field label="E-mail"><input className="field" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="Senha"><input className="field" type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" variant="solid" disabled={busy}>{busy ? "Entrando…" : "Entrar"}</Button>
        <p className="text-center text-gray">Ainda não tem conta? <Link to="/cadastro" className="text-primary underline">Cadastre-se</Link></p>
      </form>
    </div>
  );
}
