import { useNavigate } from "react-router-dom";
import { googleLoginUrl } from "../api";

export function LoginPage() {
  const navigate = useNavigate();
  return (
    <div className="flex min-h-full flex-col items-center justify-center px-6">
      <div className="w-full max-w-sm rounded-2xl border border-zinc-800 bg-zinc-900/60 p-8 shadow-xl backdrop-blur">
        <h1 className="text-2xl font-semibold tracking-tight text-white">Inbox Concierge</h1>
        <p className="mt-2 text-sm text-zinc-400">
          Sign in with Google to classify your Gmail threads with an LLM.
        </p>
        <a
          href={googleLoginUrl()}
          className="mt-8 flex w-full items-center justify-center rounded-xl bg-white px-4 py-3 text-sm font-medium text-zinc-900 transition hover:bg-zinc-100"
        >
          Continue with Google
        </a>
        <button
          type="button"
          onClick={() => navigate("/")}
          className="mt-4 w-full text-center text-sm text-zinc-500 hover:text-zinc-300"
        >
          Back
        </button>
      </div>
    </div>
  );
}
