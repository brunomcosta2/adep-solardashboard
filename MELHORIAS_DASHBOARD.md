# Plano de Implementação - Melhorias do Dashboard

## Checklist de Implementação

### 1. Indicador de Atualização + Countdown
- [x] Adicionar elemento HTML para mostrar "A atualizar..." durante fetch
- [x] Adicionar countdown timer mostrando tempo até próxima atualização
- [x] Atualizar countdown a cada segundo
- [x] Resetar countdown após atualização bem-sucedida
- [x] Estilizar indicador (spinner pequeno + texto)

### 2. Scroll Automático na Tabela
- [ ] Implementar scroll automático vertical na tabela
- [ ] Configurar velocidade e pausa no topo/fim
- [ ] Pausar scroll no hover (opcional)
- [ ] Garantir scroll suave e contínuo

### 4. Melhor Tratamento de Erros na UI
- [ ] Criar área de notificação de erros visível
- [ ] Mostrar mensagens de erro quando API falha
- [ ] Estilizar erros (vermelho, ícone de alerta)
- [ ] Auto-ocultar após X segundos ou manter até resolver

### 5. Indicador de Status de Conexão
- [ ] Adicionar indicador visual (verde/vermelho) no header
- [ ] Mostrar "Conectado" / "Desconectado"
- [ ] Detectar falhas de conexão
- [ ] Mostrar timestamp da última conexão bem-sucedida

### 6. Animações de Transição de Valores
- [ ] Adicionar animação quando valores mudam nos cards KPI
- [ ] Usar fade ou highlight temporário
- [ ] Destacar valores que aumentaram/diminuíram
- [ ] Transições suaves (CSS transitions)

### 8. Tooltips Informativos
- [ ] Adicionar tooltips nos cards KPI
- [ ] Adicionar tooltips nas colunas da tabela
- [ ] Usar atributo `title` ou biblioteca de tooltips
- [ ] Textos explicativos úteis

### 9. Estatísticas Adicionais
- [ ] Calcular percentagem de autoconsumo
- [ ] Calcular eficiência (produção/capacidade instalada)
- [ ] Adicionar card ou seção para estatísticas
- [ ] Formatar percentagens e valores

### 10. Indicador de Dados em Cache
- [ ] Adicionar campo no API response indicando se é cache
- [ ] Mostrar badge/indicador "Cache" ou "Dados frescos"
- [ ] Mostrar idade do cache (ex: "Atualizado há 2 min")
- [ ] Estilizar diferentemente (cache = amarelo, fresh = verde)

### 11. Não indicar instalação "Sem Produção" à noite
- [ ] Validar pôr do sol + alerta sem produção e ignorar o alerta

---

## Detalhamento Técnico por Item

### 1. Indicador de Atualização + Countdown

**Arquivos a modificar:**
- `templates/index.html` - Adicionar elemento HTML
- `static/script.js` - Implementar lógica de countdown
- `static/style.css` - Estilizar indicador

**Implementação:**

**HTML (templates/index.html):**
```html
<div id="update-status" style="margin-top: 5px; font-size: 0.85em;">
  <span id="update-indicator">🔄</span>
  <span id="next-update-countdown">Próxima atualização em: --:--</span>
</div>
```

**JavaScript (static/script.js):**
- Variável para rastrear tempo até próxima atualização (5 minutos = 300 segundos)
- `setInterval` para atualizar countdown a cada segundo
- Mostrar spinner durante fetch
- Resetar countdown após atualização bem-sucedida
- Formatar tempo como MM:SS

**CSS (static/style.css):**
- Estilizar indicador e countdown
- Animação do spinner (rotação)
- Cores apropriadas (verde quando próximo, amarelo quando longe)

---

### 2. Scroll Automático na Tabela

**Arquivos a modificar:**
- `static/script.js` - Implementar lógica de scroll
- `static/style.css` - Adicionar estilos para scroll suave
- `templates/index.html` - Adicionar wrapper para tabela se necessário

**Implementação:**

**JavaScript (static/script.js):**
```javascript
// Auto-scroll da tabela
let scrollDirection = 1; // 1 = down, -1 = up
let scrollSpeed = 1; // pixels por frame
let scrollPause = 2000; // pausa no topo/fim (ms)
let isScrolling = true;
let scrollPaused = false;

function autoScrollTable() {
  const tableWrapper = document.querySelector('.table-wrapper') || 
                       document.querySelector('table').parentElement;
  if (!tableWrapper || !isScrolling) return;
  
  const currentScroll = tableWrapper.scrollTop;
  const maxScroll = tableWrapper.scrollHeight - tableWrapper.clientHeight;
  
  // Pausar no topo ou fim
  if (currentScroll <= 0 || currentScroll >= maxScroll) {
    if (!scrollPaused) {
      scrollPaused = true;
      setTimeout(() => {
        scrollDirection *= -1; // Inverter direção
        scrollPaused = false;
      }, scrollPause);
    }
    return;
  }
  
  // Scroll contínuo
  tableWrapper.scrollTop += scrollSpeed * scrollDirection;
  
  requestAnimationFrame(autoScrollTable);
}

// Pausar scroll no hover (opcional)
document.querySelector('table')?.addEventListener('mouseenter', () => {
  isScrolling = false;
});

document.querySelector('table')?.addEventListener('mouseleave', () => {
  isScrolling = true;
  autoScrollTable();
});

// Iniciar scroll após carregar dados
autoScrollTable();
```

**CSS (static/style.css):**
- `scroll-behavior: smooth` para scroll suave
- Adicionar wrapper com altura fixa e overflow se necessário

---

### 4. Melhor Tratamento de Erros na UI

**Arquivos a modificar:**
- `templates/index.html` - Adicionar área de notificação
- `static/script.js` - Capturar e exibir erros
- `static/style.css` - Estilizar notificações de erro

**Implementação:**

**HTML (templates/index.html):**
```html
<div id="error-notification" class="error-notification hidden">
  <span class="error-icon">❌</span>
  <span class="error-message">Erro ao carregar dados. A tentar novamente...</span>
  <span class="error-retry-countdown"></span>
</div>
```

**JavaScript (static/script.js):**
- Capturar erros no `fetchLiveData()`
- Mostrar/ocultar notificação com classes CSS
- Implementar retry automático após X segundos (ex: 30s)
- Contador de tentativas
- Limpar notificação quando sucesso

**CSS (static/style.css):**
- Estilo para `.error-notification` (vermelho, destaque)
- Animação de entrada/saída
- Posicionamento fixo ou no topo da página

---

### 5. Indicador de Status de Conexão

**Arquivos a modificar:**
- `templates/index.html` - Adicionar indicador no header
- `static/script.js` - Lógica de detecção de conexão
- `static/style.css` - Estilizar indicador

**Implementação:**

**HTML (templates/index.html):**
```html
<div id="connection-status" style="display: inline-block; margin-left: 20px;">
  <span id="connection-indicator">🟢</span>
  <span id="connection-text">Conectado</span>
  <span id="last-connection-time" style="font-size: 0.8em; margin-left: 5px;"></span>
</div>
```

**JavaScript (static/script.js):**
- Detectar sucesso/falha de fetch
- Atualizar indicador visual (🟢/🔴)
- Atualizar texto "Conectado"/"Desconectado"
- Armazenar timestamp da última conexão bem-sucedida
- Mostrar "Última conexão: HH:MM:SS"

**CSS (static/style.css):**
- Estilizar indicador
- Animações para mudanças de estado

---

### 6. Animações de Transição de Valores

**Arquivos a modificar:**
- `static/script.js` - Comparar valores e aplicar animações
- `static/style.css` - Definir animações CSS

**Implementação:**

**CSS (static/style.css):**
```css
.value {
  transition: all 0.3s ease;
}

.value-updated {
  animation: highlightUpdate 0.5s ease;
}

.value-increased {
  animation: highlightIncrease 0.5s ease;
}

.value-decreased {
  animation: highlightDecrease 0.5s ease;
}

@keyframes highlightUpdate {
  0% { background-color: rgba(76, 175, 80, 0.3); }
  100% { background-color: transparent; }
}

@keyframes highlightIncrease {
  0% { background-color: rgba(76, 175, 80, 0.4); transform: scale(1.05); }
  100% { background-color: transparent; transform: scale(1); }
}

@keyframes highlightDecrease {
  0% { background-color: rgba(244, 67, 54, 0.4); transform: scale(0.95); }
  100% { background-color: transparent; transform: scale(1); }
}
```

**JavaScript (static/script.js):**
- Armazenar valores anteriores dos KPIs
- Comparar valores antigos vs novos após cada atualização
- Aplicar classe de animação apropriada quando valor mudar
- Remover classe após animação completar
- Detectar se valor aumentou ou diminuiu

---

### 8. Tooltips Informativos

**Arquivos a modificar:**
- `templates/index.html` - Adicionar atributos `title` ou `data-tooltip`
- `static/script.js` - Implementar tooltips customizados (opcional)
- `static/style.css` - Estilizar tooltips

**Implementação:**

**HTML (templates/index.html):**
- Adicionar `title` nos cards KPI:
  - Produção: "Energia total gerada pelas instalações solares"
  - Consumo: "Energia total consumida pela instalação"
  - Consumo da Rede: "Energia consumida da rede elétrica"
  - Instalações: "Número total de instalações monitorizadas"

- Adicionar `title` nas colunas da tabela:
  - Potência Instalada: "Capacidade total de geração instalada"
  - Produção: "Energia gerada no momento"
  - Consumo Total: "Energia total consumida"
  - Consumo da Rede: "Energia consumida da rede (valores positivos)"
  - Excedente: "Energia excedente injetada na rede"

**CSS (static/style.css):**
- Estilizar tooltips nativos do browser (limitado)
- Ou implementar tooltips customizados com CSS e JavaScript

---

### 9. Estatísticas Adicionais

**Arquivos a modificar:**
- `app.py` - Calcular estatísticas no backend
- `templates/index.html` - Adicionar card/seção para estatísticas
- `static/script.js` - Exibir estatísticas
- `static/style.css` - Estilizar novo card

**Implementação:**

**Backend (app.py):**
- No endpoint `/api/live-data`, calcular:
  - **Autoconsumo (%):** `(self_consumption / production) * 100`
    - Onde `self_consumption = min(production, consumption)`
  - **Eficiência (%):** `(production / total_capacity) * 100`
    - Onde `total_capacity = sum(pinstalled)` de todas as plantas
- Adicionar ao response JSON:
```python
"statistics": {
    "self_consumption_percent": 75.5,
    "efficiency_percent": 45.2
}
```

**Frontend (templates/index.html):**
- Adicionar novo card KPI ou seção dedicada:
```html
<div class="card" id="stats">
  <div class="card-label">Estatísticas</div>
  <div class="card-value">
    <div>Autoconsumo: <span id="self-consumption">--%</span></div>
    <div>Eficiência: <span id="efficiency">--%</span></div>
  </div>
</div>
```

**JavaScript (static/script.js):**
- Atualizar valores de estatísticas após fetch
- Formatar percentagens com 1 casa decimal

**CSS (static/style.css):**
- Estilizar novo card de estatísticas
- Adicionar border-left colorida

---

### 10. Indicador de Dados em Cache

**Arquivos a modificar:**
- `app.py` - Adicionar campos de cache ao response
- `templates/index.html` - Adicionar badge/indicador
- `static/script.js` - Exibir indicador de cache
- `static/style.css` - Estilizar badge

**Implementação:**

**Backend (app.py):**
- No endpoint `/api/live-data`, verificar se dados são do cache
- Adicionar ao response JSON:
```python
"cache_info": {
    "is_cached": True/False,
    "cache_age_seconds": 120,  # idade do cache em segundos
    "cache_age_formatted": "2 min"  # formato legível
}
```

**Frontend (templates/index.html):**
- Adicionar badge próximo ao "Última atualização":
```html
<span id="cache-badge" class="cache-badge hidden">
  <span id="cache-indicator">Cache</span>
  <span id="cache-age">há 2 min</span>
</span>
```

**JavaScript (static/script.js):**
- Mostrar/ocultar badge baseado em `is_cached`
- Atualizar idade do cache
- Formatar tempo (segundos → "X min", "X seg")

**CSS (static/style.css):**
- Estilizar badge:
  - Cache: fundo amarelo/laranja, texto escuro
  - Dados frescos: fundo verde, texto claro (ou ocultar)
- Posicionamento e tamanho apropriados

---

## Ordem Sugerida de Implementação

1. **Indicador de Atualização + Countdown** (mais visível para o usuário)
2. **Scroll Automático na Tabela** (melhora UX em modo kiosk)
3. **Tratamento de Erros na UI** (importante para robustez)
4. **Indicador de Status de Conexão** (complementa o anterior)
5. **Animações de Transição** (melhora visual)
6. **Indicador de Dados em Cache** (informação útil)
7. **Tooltips Informativos** (ajuda contextual)
8. **Estatísticas Adicionais** (mais complexo, deixar por último)

---

## Estimativa de Complexidade

- **Fácil (1-2 horas):** Itens 1, 2, 4, 5, 6
- **Média (2-3 horas):** Itens 8, 10
- **Mais Complexo (3-4 horas):** Item 9 (requer cálculos no backend)

---

## Notas de Implementação

- O intervalo de atualização atual é de **5 minutos** (300 segundos)
- A tabela pode precisar de um wrapper com altura fixa para scroll funcionar corretamente
- As animações devem ser sutis para não distrair em modo kiosk
- Tooltips podem ser simples (atributo `title`) ou customizados para melhor controle visual
- Estatísticas adicionais requerem cálculos precisos no backend para evitar divisão por zero

---

## Status

- [x] Item 1 - Indicador de Atualização + Countdown
- [ ] Item 2 - Scroll Automático na Tabela
- [ ] Item 4 - Tratamento de Erros na UI
- [ ] Item 5 - Indicador de Status de Conexão
- [ ] Item 6 - Animações de Transição
- [ ] Item 8 - Tooltips Informativos
- [ ] Item 9 - Estatísticas Adicionais
- [ ] Item 10 - Indicador de Dados em Cache

