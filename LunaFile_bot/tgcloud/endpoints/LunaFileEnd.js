import { EndpointError } from 'sdk';

// LunaFileEnd — an HTTP endpoint of the Mini App.
// Once deployed, it answers at POST /api/LunaFileEnd.
export default async function (input, ctx) {
  // The platform verifies Telegram Mini App init data before this endpoint runs.
  const user = ctx.initData?.user;

  if (!user || !Number.isSafeInteger(user.id)) {
    throw new EndpointError('Telegram user information is unavailable.', {
      code: 'USER_REQUIRED',
    });
  }

  return {
    app: 'LunaFile',
    user: {
      id: user.id,
      firstName: user.first_name ?? '',
      lastName: user.last_name ?? '',
      username: user.username ?? null,
      languageCode: user.language_code ?? null,
    },
    welcome: `Welcome to LunaFile${user.first_name ? `, ${user.first_name}` : ''}!`,
  };
}
