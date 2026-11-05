export const runtime='nodejs';
export const dynamic='force-dynamic';
export async function GET(){return Response.json({ok:true,service:'lunafile-nextjs',time:new Date().toISOString()});}
