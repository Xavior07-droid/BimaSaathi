'use client';
import Link from 'next/link';
import Icon, { type IconName } from './Icon';

interface Props {
  title: string;
  body?: string;
  icon?: IconName;
  action?: { label: string; href: string };
}

/** Friendly "nothing here" screen (also reused for missing ?id= params). */
export default function EmptyState({ title, body, icon = 'info', action }: Props) {
  return (
    <div className="card flex flex-col items-center gap-3 py-8 text-center">
      <span className="flex h-14 w-14 items-center justify-center rounded-full bg-brand-100 text-brand-800">
        <Icon name={icon} className="h-7 w-7" />
      </span>
      <h2>{title}</h2>
      {body && <p className="text-ink-soft">{body}</p>}
      {action && (
        <Link href={action.href} className="btn-primary mt-2 w-full">
          {action.label}
        </Link>
      )}
    </div>
  );
}
