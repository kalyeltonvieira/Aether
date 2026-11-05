import { expect, test } from '@playwright/test';

const testToken = process.env.AETHER_OPERATOR_TOKEN ?? 'aether-e2e-test-token-not-for-production';

test('fluxo real: entidades, fatos, conclusão, prova, remoção e histórico', async ({ page }, testInfo) => {
  await page.goto('/');
  await page.getByLabel('Token da instalação').fill(testToken);
  await page.getByRole('button', { name: 'Abrir sessão' }).click();
  await expect(page.getByRole('navigation', { name: 'Navegação principal' })).toBeVisible();
  await page.getByRole('link', { name: 'Knowledge Explorer', exact: true }).click();
  await page.getByRole('tab', { name: 'Entidades', exact: true }).click();
  for (const id of ['e2e-alice', 'e2e-bob']) {
    await page.getByRole('button', { name: 'Nova entidade', exact: true }).click();
    await page.getByLabel('Entity ID', { exact: true }).fill(id);
    await page.getByRole('button', { name: 'Criar entidade', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('cell', { name: id, exact: true })).toBeVisible();
  }
  await page.getByRole('tab', { name: 'Fatos', exact: true }).click();
  await page.getByRole('button', { name: 'Novo fato', exact: true }).click();
  await page.getByLabel('Fato sujeito', { exact: true }).fill('e2e-alice');
  await page.getByLabel('Fato predicado', { exact: true }).fill('e2e_sent_email');
  await page.getByLabel('Fato objeto', { exact: true }).fill('e2e-bob');
  await page.getByLabel('Fato fonte', { exact: true }).fill('e2e-browser-fixture');
  await page.getByRole('button', { name: 'Criar fato', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('cell', { name: 'e2e_sent_email', exact: true })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('studio-knowledge-with-real-fact.png'), fullPage: true });
  await page.goto('/graph');
  await expect(page.locator('.react-flow__node').filter({ hasText: 'e2e-alice' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('studio-graph-with-real-fact.png'), fullPage: true });
  await page.getByRole('link', { name: 'Reasoning Console', exact: true }).click();
  await page.getByRole('button', { name: 'Nova regra', exact: true }).click();
  await page.getByLabel('Rule ID', { exact: true }).fill('e2e-email-implies-contact');
  await page.getByLabel('Se 1 sujeito', { exact: true }).fill('?x');
  await page.getByLabel('Se 1 predicado', { exact: true }).fill('e2e_sent_email');
  await page.getByLabel('Se 1 objeto', { exact: true }).fill('?y');
  await page.getByLabel('Então sujeito', { exact: true }).fill('?x');
  await page.getByLabel('Então predicado', { exact: true }).fill('e2e_contacted');
  await page.getByLabel('Então objeto', { exact: true }).fill('?y');
  await page.getByRole('button', { name: 'Persistir regra', exact: true }).click();
  await expect(page.getByText('e2e-email-implies-contact', { exact: true })).toBeVisible();
  await page.getByLabel('Sujeito da consulta', { exact: true }).fill('?x');
  await page.getByLabel('Predicado da consulta', { exact: true }).fill('e2e_contacted');
  await page.getByLabel('Objeto da consulta', { exact: true }).fill('?y');
  await page.getByRole('button', { name: 'Executar consulta', exact: true }).click();
  await expect(page.getByText('e2e-alice · e2e_contacted · e2e-bob', { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('studio-reasoning-with-real-conclusion.png'), fullPage: true });
  await page.getByRole('link', { name: 'Proof Explorer', exact: true }).click();
  await page.getByLabel('Sujeito', { exact: true }).fill('e2e-alice');
  await page.getByLabel('Predicado', { exact: true }).fill('e2e_contacted');
  await page.getByLabel('Objeto', { exact: true }).fill('e2e-bob');
  await page.getByRole('button', { name: 'Explicar conclusão', exact: true }).click();
  await expect(page.getByText('Regra e2e-email-implies-contact', { exact: true }).first()).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('studio-proof-with-real-support.png'), fullPage: true });
  await page.getByRole('link', { name: /^fact #\d+/ }).first().click();
  await page.getByLabel('Filtrar predicado', { exact: true }).fill('e2e_sent_email');
  page.once('dialog', async (dialog) => dialog.accept());
  await page.getByRole('button', { name: /^Remover fato \d+$/ }).first().click();
  await expect(page.getByText('Nenhum fato encontrado', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Histórico', exact: true }).click();
  await expect(page.getByText('fact_removed', { exact: true }).first()).toBeVisible();
  await page.getByRole('link', { name: 'Reasoning Console', exact: true }).click();
  await page.getByLabel('Sujeito da consulta', { exact: true }).fill('?x');
  await page.getByLabel('Predicado da consulta', { exact: true }).fill('e2e_contacted');
  await page.getByLabel('Objeto da consulta', { exact: true }).fill('?y');
  await page.getByRole('button', { name: 'Executar consulta', exact: true }).click();
  await expect(page.getByText('Nenhuma solução', { exact: true })).toBeVisible();
  await expect(page.getByText('completo', { exact: true }).first()).toBeVisible();
});

test('páginas reais sem erros de runtime e menu em viewport móvel', async ({ page }, testInfo) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/');
  await page.getByLabel('Token da instalação').fill(testToken);
  await page.getByRole('button', { name: 'Abrir sessão' }).click();
  const routes = ['/', '/knowledge', '/graph', '/reasoning', '/proofs', '/memory', '/events', '/performance', '/settings'];
  for (const [index, route] of routes.entries()) {
    await page.goto(route);
    await expect(page.locator('main.workspace')).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    await page.screenshot({ path: testInfo.outputPath(`studio-${String(index + 1).padStart(2, '0')}-${route === '/' ? 'dashboard' : route.slice(1)}.png`), fullPage: true });
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('button', { name: 'Abrir menu' }).click();
  await expect(page.getByRole('navigation', { name: 'Navegação principal' })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('studio-mobile-menu.png'), fullPage: true });
  expect(errors).toEqual([]);
});
