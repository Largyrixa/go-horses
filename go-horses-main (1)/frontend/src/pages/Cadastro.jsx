import { useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/lib/auth";
import Button from "@/components/Button";
import { ErrorNote, Field, PageTitle } from "@/components/ui";

// RF01: nome de exibição, e-mail e senha. Um e-mail identifica uma única conta.
export default function Cadastro() {
  const { register, login } = useAuth();
  const navigate = useNavigate();
  const [f, setF] = useState({ display_name: "", email: "", password: "" });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  async function submit(e) {
    e.preventDefault();
    if (f.password.length < 8) return setError("A senha precisa ter pelo menos 8 caracteres.");
    setBusy(true); setError(null);
    try {
      await register({ ...f, display_name: f.display_name.trim(), email: f.email.trim() });
      await login(f.email.trim(), f.password);
      navigate("/");
    } catch (err) {
      setError(err.status === 409 ? "Já existe uma conta com esse e-mail. Entre ou use outro e-mail." : err.message);
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto max-w-md">
      <PageTitle>Criar conta</PageTitle>
      <form onSubmit={submit} className="panel flex flex-col gap-5">
        <Field label="Nome de exibição" hint="Aparece nos leilões; no placar só mostramos seu primeiro nome e a inicial do sobrenome.">
          <input className="field" required maxLength={60} autoComplete="name" value={f.display_name} onChange={set("display_name")} />
        </Field>
        <Field label="E-mail"><input className="field" type="email" required autoComplete="email" value={f.email} onChange={set("email")} /></Field>
        <Field label="Senha" hint="Mínimo de 8 caracteres."><input className="field" type="password" required minLength={8} autoComplete="new-password" value={f.password} onChange={set("password")} /></Field>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" variant="solid" disabled={busy}>{busy ? "Criando…" : "Criar conta"}</Button>
        <p className="text-center text-gray">Já tem conta? <Link to="/login" className="text-primary underline">Entre</Link></p>
      </form>
    </div>
  );
}
