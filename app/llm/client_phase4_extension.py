async def generate_design_intent(self, user_prompt: str):
        """
        Phase 4 Stage 1: Extract design intent from user prompt.
        
        Args:
            user_prompt: User's natural language description
           
        Returns:
            DesignIntent object
        """
        from app.domain.design_intent import DesignIntent
        
        try:
            completion = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": INTENT_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": INTENT_EXTRACTION_USER_TEMPLATE.format(prompt=user_prompt)}
                ],
                temperature=0.2,
                max_tokens=512
            )
            
            raw_response = completion.choices[0].message.content.strip()
            json_content = self._extract_json(raw_response)
            intent_dict = json.loads(json_content)
            
            # Add original prompt
            intent_dict["original_prompt"] = user_prompt
            
            return DesignIntent(**intent_dict)
            
        except Exception as e:
            logger.error(f"Design intent extraction failed: {e}")
            raise
    
async def generate_from_template(self, intent):
        """
        Phase 4 Stage 2: Generate FeatureGraph from intent using template.
        
        Args:
            intent: DesignIntent object
            
        Returns:
            FeatureGraphV3
        """
        from app.templates.parametric_templates import TemplateRegistry
        
        # Select template
        template = TemplateRegistry.select_template(intent)
        if not template:
            raise ValueError(f"No template found for part_type: {intent.part_type}")
        
        # Validate intent has required dimensions
        if not template.validate_intent(intent):
            missing = [d for d in template.required_dimensions() if d not in intent.key_dimensions]
            raise ValueError(
                f"Intent missing required dimensions for {template.name}: {missing}"
            )
        
        # Generate FeatureGraph
        logger.info(f"Generating from template: {template.name}")
        feature_graph = template.generate(intent)
        
        return feature_graph
