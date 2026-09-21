export interface User {
  id: string;
  name: string;
}

export const formatUser = (user: User): string => `${user.id}:${user.name}`;
