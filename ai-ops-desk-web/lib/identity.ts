// Friendly identities for the seeded user_001..user_007 IDs.
// Real customers wouldn't see these IDs — the ops drawer shows them
// to demo operators only.

export type Identity = {
  userId: string;
  name: string;
  initials: string;
};

const IDENTITIES: Record<string, { name: string }> = {
  user_001: { name: "Sarah Chen" },
  user_002: { name: "Marcus Reed" },
  user_003: { name: "Priya Patel" },
  user_004: { name: "Diego Alvarez" },
  user_005: { name: "Jordan Blake" },
  user_006: { name: "Aiko Tanaka" },
  user_007: { name: "Sam Whitaker" },
};

export function identityFor(userId: string): Identity {
  const meta = IDENTITIES[userId] ?? { name: userId };
  const initials = meta.name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
  return { userId, name: meta.name, initials };
}

export const DEFAULT_USER_ID = "user_001";
