import { useEffect } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { AuthProvider } from "@/lib/auth";
import Nav from "@/components/Nav";
import Footer from "@/components/Footer";
import Button from "@/components/Button";
import { Empty } from "@/components/ui";
import Home from "@/pages/Home";
import Login from "@/pages/Login";
import Cadastro from "@/pages/Cadastro";
import NovoLeilao from "@/pages/NovoLeilao";
import Detalhe from "@/pages/Detalhe";
import Sala from "@/pages/Sala";
import Participacoes from "@/pages/Participacoes";
import MeusLeiloes from "@/pages/MeusLeiloes";
import Comitentes from "@/pages/Comitentes";
import Perfil from "@/pages/Perfil";
import Relistar from "@/pages/Relistar";

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => { window.scrollTo(0, 0); }, [pathname]);
  return null;
}

const ADMIN_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ";

function AdminRedirect() {
  useEffect(() => {
    window.location.replace(ADMIN_URL);
  }, []);
  return <p className="text-gray" role="status">Redirecionando…</p>;
}

export default function App() {
  return (
    <>
      <div className="crt-overlay" aria-hidden="true" />
      <AuthProvider>
        <ScrollToTop />
        <Nav />
        <main className="mx-auto min-h-screen max-w-6xl px-5 pb-16 pt-28">
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/login" element={<Login />} />
            <Route path="/cadastro" element={<Cadastro />} />
            <Route path="/leiloes/novo" element={<NovoLeilao />} />
            <Route path="/leiloes/:id" element={<Detalhe />} />
            <Route path="/leiloes/:id/sala" element={<Sala />} />
            <Route path="/leiloes/:id/relistar" element={<Relistar />} />
            <Route path="/comitentes" element={<Comitentes />} />
            <Route path="/comitentes/:id" element={<Perfil />} />
            <Route path="/minhas-participacoes" element={<Participacoes />} />
            <Route path="/meus-leiloes" element={<MeusLeiloes />} />
            <Route path="/admin" element={<AdminRedirect />} />
            <Route path="*" element={<Empty action={<Button href="/">Voltar aos leilões</Button>}>Página não encontrada.</Empty>} />
          </Routes>
        </main>
        <Footer />
      </AuthProvider>
    </>
  );
}
