import { useState } from "react";
import { Link } from "react-router-dom";
import { Menu, X } from "lucide-react";
import { useAuth } from "@/lib/auth";

export default function Nav() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);

  const links = user
    ? [
        { name: "Leilões", href: "/" },
        { name: "Comitentes", href: "/comitentes" },
        { name: "Anunciar", href: "/leiloes/novo" },
        { name: "Meus leilões", href: "/meus-leiloes" },
        { name: "Participações", href: "/minhas-participacoes" },
      ]
    : [
        { name: "Leilões", href: "/" },
        { name: "Comitentes", href: "/comitentes" },
        { name: "Entrar", href: "/login" },
        { name: "Cadastrar", href: "/cadastro" },
      ];

  const item = "font-mono text-sm uppercase tracking-widest text-white/90 transition-colors hover:text-primary";
  const bracket = (n) => (<><span className="text-soft">[</span>{n}<span className="text-soft">]</span></>);

  return (
    <header className="fixed left-0 top-0 z-50 w-full border-b border-primary/20 bg-black/60 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-4">
        <Link to="/" className="font-display text-xl uppercase tracking-wider text-white transition-colors hover:text-primary">
          Go Horses<span className="ml-1 text-primary motion-safe:animate-pulse">_</span>
        </Link>

        <nav className="hidden items-center gap-8 lg:flex" aria-label="Principal">
          {links.map((l) => (<Link key={l.href} to={l.href} className={item}>{bracket(l.name)}</Link>))}
          {user && (
            <button onClick={logout} className={`${item} text-gray`} title={user.display_name}>{bracket("Sair")}</button>
          )}
        </nav>

        <button className="text-white lg:hidden" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={open ? "Fechar menu" : "Abrir menu"}>
          {open ? <X /> : <Menu />}
        </button>
      </div>

      {open && (
        <nav className="flex flex-col gap-5 border-t border-edge px-5 py-6 lg:hidden" aria-label="Principal (mobile)">
          {links.map((l) => (<Link key={l.href} to={l.href} onClick={() => setOpen(false)} className={item}>{bracket(l.name)}</Link>))}
          {user && <button onClick={() => { setOpen(false); logout(); }} className={`${item} text-left text-gray`}>{bracket("Sair")}</button>}
        </nav>
      )}
    </header>
  );
}
