export interface M09LoopbackEndpoint {
  readonly origin: string;
  readonly hostname: string;
  readonly port: number;
}

export type M09Environment = Readonly<Record<string, string | undefined>>;

export function assertM09LoopbackUrl(
  name: string,
  rawValue: string,
): M09LoopbackEndpoint;

export function resolveM09Urls(environment?: M09Environment): Readonly<{
  app: M09LoopbackEndpoint;
  api: M09LoopbackEndpoint;
}>;
