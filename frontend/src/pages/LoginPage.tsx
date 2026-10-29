import { useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiError } from "../api/client";
import { useAuth } from "../app/auth-context";
import { Logo } from "../components/Logo";
import { Button, Field } from "../components/ui";

interface LoginForm {
  email: string;
  password: string;
}

export function LoginPage(): ReactNode {
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [formError, setFormError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginForm>();

  // Return the user to the page they were sent from (e.g. a deep link to a candidate's
  // resume download opened from the Excel export), falling back to the dashboard. Only
  // same-origin internal paths are honoured so an attacker cannot craft an open redirect.
  const rawFrom = (location.state as { from?: string } | null)?.from;
  const redirectTo = typeof rawFrom === "string" && rawFrom.startsWith("/") ? rawFrom : "/";

  async function onSubmit(values: LoginForm): Promise<void> {
    setFormError(null);
    try {
      await signIn(values.email, values.password);
      navigate(redirectTo, { replace: true });
    } catch (err) {
      setFormError(
        err instanceof ApiError
          ? "Sign in failed. Check your details and try again."
          : "Unexpected error. Is the API running on :8000?",
      );
    }
  }

  return (
    <div className="auth-wrap">
      <section className="auth-hero" aria-hidden="true">
        <Logo size={64} title="Orient Recruitment Accelerator" />
        <h1 style={{ marginTop: 20 }}>Orient Recruitment Accelerator</h1>
        <p style={{ color: "#cfe0f2", maxWidth: 440 }}>
          A secure, explainable platform for recruitment campaigns and candidate screening — with
          deterministic rules, human-approved decisions, and a full audit trail.
        </p>
        <ul>
          <li>Project &amp; campaign management with versioned JDs and rules</li>
          <li>Deterministic, explainable screening — never auto-rejects</li>
          <li>Human review, interviews, waitlist and talent pool</li>
          <li>Privacy, retention and governance built in</li>
        </ul>
      </section>

      <section className="auth-panel">
        <div className="auth-card">
          <h1 id="login-heading">Sign in</h1>
          <p className="subtle">Use your staff account to continue.</p>

          {formError && (
            <div className="error-summary" role="alert" aria-live="assertive">
              {formError}
            </div>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate>
            <Field label="Email" htmlFor="email" error={errors.email?.message}>
              <input
                id="email"
                type="email"
                autoComplete="username"
                aria-invalid={errors.email ? "true" : undefined}
                {...register("email", { required: "Email is required" })}
              />
            </Field>
            <Field label="Password" htmlFor="password" error={errors.password?.message}>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={errors.password ? "true" : undefined}
                {...register("password", { required: "Password is required" })}
              />
            </Field>
            <Button variant="primary" type="submit" disabled={isSubmitting} style={{ width: "100%" }}>
              {isSubmitting ? "Signing in…" : "Sign in"}
            </Button>
          </form>
        </div>
      </section>
    </div>
  );
}
