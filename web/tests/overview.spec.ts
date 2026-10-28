import {test,expect} from '@playwright/test'
test('dashboard can navigate to live views',async({page})=>{
 await page.goto('/')
 await expect(page.getByRole('heading',{name:'Overview'})).toBeVisible()
 await page.getByRole('button',{name:'Traces',exact:true}).click()
 await expect(page.getByRole('heading',{name:'Recent distributed traces'})).toBeVisible()
 await page.getByRole('button',{name:'Lab',exact:true}).click()
 await expect(page.getByRole('heading',{name:'Isolated fault-injection laboratory'})).toBeVisible()
})
